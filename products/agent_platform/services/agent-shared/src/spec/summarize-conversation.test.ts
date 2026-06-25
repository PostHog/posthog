import { AssistantMessageRecord, ConversationMessage, EMPTY_USAGE_TOTAL, ToolResultMessage, UserMessage } from './spec'
import {
    accumulateUsage,
    buildSearchText,
    lastAssistantTextPreview,
    previewText,
    totalConversationUsage,
} from './summarize-conversation'

function user(content: string): UserMessage {
    return { role: 'user', content, timestamp: Date.now() }
}

interface AssistantOpts {
    text?: string
    input?: number
    output?: number
    costIn?: number
    costOut?: number
}

function assistant({
    text = '',
    input = 0,
    output = 0,
    costIn = 0,
    costOut = 0,
}: AssistantOpts = {}): AssistantMessageRecord {
    return {
        role: 'assistant',
        content: text ? [{ type: 'text', text }] : [],
        api: 'anthropic-messages',
        provider: 'anthropic',
        model: 'anthropic/claude-haiku-4-5',
        usage: {
            input,
            output,
            cost: { input: costIn, output: costOut, total: costIn + costOut },
        },
        timestamp: Date.now(),
    }
}

describe('lastAssistantTextPreview', () => {
    it('returns null when no assistant turn exists yet', () => {
        expect(lastAssistantTextPreview([])).toBeNull()
        expect(lastAssistantTextPreview([user('hi')])).toBeNull()
    })

    it('returns the latest assistant text block, collapsing whitespace', () => {
        const c: ConversationMessage[] = [
            user('first'),
            assistant({ text: 'first answer' }),
            user('second'),
            assistant({ text: 'second\n  answer  with   gaps' }),
        ]
        expect(lastAssistantTextPreview(c)).toBe('second answer with gaps')
    })

    it('truncates with an ellipsis past the max length', () => {
        const long = 'a'.repeat(200)
        const preview = lastAssistantTextPreview([assistant({ text: long })])
        expect(preview).toHaveLength(120)
        expect(preview!.endsWith('…')).toBe(true)
    })

    it('honors a custom max', () => {
        const preview = lastAssistantTextPreview([assistant({ text: 'hello world' })], 5)
        expect(preview).toBe('hell…')
    })

    it('does not split an emoji surrogate pair at the truncation boundary', () => {
        // With max=4, a naive `slice(0, 3)` cuts "👋" (👋) in half and
        // leaves a lone high surrogate — invalid UTF-8 that crashes JSON
        // serialization downstream (orjson refuses it). The preview must keep
        // the emoji whole.
        const preview = lastAssistantTextPreview([assistant({ text: 'ab👋cd' })], 4)
        expect(preview).toBe('ab👋…')
        // No unpaired surrogate survives.
        expect(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(preview!)).toBe(false)
    })

    it('skips assistant turns that have no text block (e.g. tool calls only)', () => {
        const c: ConversationMessage[] = [
            assistant({ text: 'visible reply' }),
            // No text block — only tool calls would land here in practice.
            { ...assistant({}), content: [] },
        ]
        expect(lastAssistantTextPreview(c)).toBe('visible reply')
    })
})

describe('buildSearchText', () => {
    function toolResult(text: string): ToolResultMessage {
        return {
            role: 'toolResult',
            toolCallId: 'tc1',
            toolName: 'bash',
            content: [{ type: 'text', text }],
            isError: false,
            timestamp: Date.now(),
        }
    }

    it('joins user + assistant text in order, collapsing whitespace', () => {
        const c: ConversationMessage[] = [user('deploy the  widget'), assistant({ text: 'on\n  it' }), user('thanks')]
        expect(buildSearchText(c)).toBe('deploy the widget on it thanks')
    })

    it('skips tool results and text-less assistant turns', () => {
        const c: ConversationMessage[] = [
            user('run it'),
            toolResult('SECRET_TOKEN=abc noise that should not be searchable'),
            { ...assistant({}), content: [] },
            assistant({ text: 'done' }),
        ]
        expect(buildSearchText(c)).toBe('run it done')
    })

    it('truncates to the max code points without an ellipsis', () => {
        const out = buildSearchText([user('a'.repeat(50))], 10)
        expect(out).toBe('a'.repeat(10))
    })

    it('handles array-form user content', () => {
        const c: ConversationMessage[] = [
            { role: 'user', content: [{ type: 'text', text: 'hello' }], timestamp: Date.now() },
        ]
        expect(buildSearchText(c)).toBe('hello')
    })

    it('strips the slack envelope + mention, keeping the real message', () => {
        const slack = user(
            [
                '[slack]',
                'channel: C0BA3AC9TT2',
                'ts: 1782215525.31',
                'thread_ts: 1782215525.31',
                'user: U03DCBD92JX',
                'mention: true',
                'dm: false',
                '',
                '<@U0BCBQVL62G> what happened today?',
            ].join('\n')
        )
        expect(buildSearchText([slack, assistant({ text: 'A few things.' })])).toBe(
            'what happened today? A few things.'
        )
    })

    it('strips the [console-context] block, keeping the real message', () => {
        const consoleMsg = user(
            '[console-context]\n{"page":"agent","project_id":1}\n[/console-context]\n\ncan you test out this agent'
        )
        expect(buildSearchText([consoleMsg])).toBe('can you test out this agent')
    })

    it('leaves cron / plain messages untouched', () => {
        expect(buildSearchText([user('Build the morning briefing for 2026-06-23.')])).toBe(
            'Build the morning briefing for 2026-06-23.'
        )
    })
})

describe('previewText', () => {
    it('returns null for null/empty', () => {
        expect(previewText(null)).toBeNull()
        expect(previewText('   ')).toBeNull()
    })

    it('collapses and truncates with an ellipsis', () => {
        expect(previewText('hi   there', 4)).toBe('hi …')
    })
})

describe('totalConversationUsage', () => {
    it('returns all zeros for an empty conversation', () => {
        expect(totalConversationUsage([])).toEqual({
            tokens_in: 0,
            tokens_out: 0,
            cache_read: 0,
            cache_write: 0,
            cost_input: 0,
            cost_output: 0,
            cost_cache_read: 0,
            cost_cache_write: 0,
            cost_total: 0,
        })
    })

    it('aggregates token counts across assistant turns but never pi-estimated cost', () => {
        const c: ConversationMessage[] = [
            user('q1'),
            assistant({ text: 'a1', input: 100, output: 10, costIn: 0.001, costOut: 0.0005 }),
            user('q2'),
            assistant({ text: 'a2', input: 50, output: 5, costIn: 0.0005, costOut: 0.0003 }),
        ]
        const total = totalConversationUsage(c)
        expect(total.tokens_in).toBe(150)
        expect(total.tokens_out).toBe(15)
        // pi-ai's per-message cost estimates are never trusted — cost is owned
        // by the gateway settlement merged onto the persisted column, not here.
        expect(total.cost_input).toBe(0)
        expect(total.cost_output).toBe(0)
        expect(total.cost_total).toBe(0)
    })

    it('ignores user / toolResult messages and assistant turns missing usage', () => {
        const noUsage = assistant({ text: 'no-usage reply' })
        noUsage.usage = undefined
        const c: ConversationMessage[] = [
            user('q'),
            noUsage,
            assistant({ text: 'counted reply', input: 7, output: 1, costIn: 0, costOut: 0 }),
        ]
        const total = totalConversationUsage(c)
        expect(total.tokens_in).toBe(7)
        expect(total.tokens_out).toBe(1)
    })
})

describe('accumulateUsage', () => {
    it('folds token counts into a running total but never pi-estimated cost', () => {
        const msg = assistant({ input: 10, output: 2, costIn: 0.1, costOut: 0.05 })
        const after = accumulateUsage(EMPTY_USAGE_TOTAL, msg)
        expect(after.tokens_in).toBe(10)
        expect(after.tokens_out).toBe(2)
        // Cost is never taken from pi-ai's estimate, even when the message reports it.
        expect(after.cost_input).toBe(0)
        expect(after.cost_output).toBe(0)
        expect(after.cost_total).toBe(0)
    })

    it('carries prior cost forward unchanged — gateway settlement owns cost_total', () => {
        // The driver merges the gateway's settled /v1/usage figure into
        // cost_total post-turn; accumulateUsage must preserve it, not clobber or
        // add a pi estimate on top.
        const prev = { ...EMPTY_USAGE_TOTAL, cost_total: 0.42 }
        const msg = assistant({ input: 10, output: 2, costIn: 0.1, costOut: 0.05 })
        const after = accumulateUsage(prev, msg)
        expect(after.tokens_in).toBe(10)
        expect(after.cost_total).toBe(0.42)
    })

    it('returns the prev total unchanged when the message has no usage', () => {
        const noUsage = assistant({ text: 'noop' })
        noUsage.usage = undefined
        const prev = { ...EMPTY_USAGE_TOTAL, tokens_in: 42 }
        const after = accumulateUsage(prev, noUsage)
        expect(after).toEqual(prev)
    })
})
