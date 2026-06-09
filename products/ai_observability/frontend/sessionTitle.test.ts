import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { resolveSessionTitle } from './sessionTitle'

function makeEvent(
    id: string,
    event: string,
    createdAt: string,
    properties: Record<string, unknown> = {}
): LLMTraceEvent {
    return { id, event, createdAt, properties }
}

function makeTrace(events: LLMTraceEvent[], overrides: Partial<LLMTrace> = {}): LLMTrace {
    return {
        id: 't1',
        createdAt: events[0]?.createdAt ?? '2026-05-29T00:00:00.000Z',
        distinctId: 'user-1',
        events,
        ...overrides,
    }
}

describe('resolveSessionTitle', () => {
    it('returns null when the trace is undefined', () => {
        expect(resolveSessionTitle(undefined)).toBeNull()
    })

    it('returns null when no signal is available', () => {
        const trace = makeTrace([], { traceName: 'LangGraph' })
        expect(resolveSessionTitle(trace)).toBeNull()
    })

    it('prefers the first user-role message in trace.inputState.messages', () => {
        const trace = makeTrace([], {
            traceName: 'LangGraph',
            inputState: {
                messages: [
                    { role: 'system', content: 'system prompt' },
                    { role: 'user', content: 'how do I add a feature flag?' },
                    { role: 'assistant', content: 'reply' },
                ],
            },
        })
        expect(resolveSessionTitle(trace)).toBe('how do I add a feature flag?')
    })

    it('treats LangChain type:"human" messages as user messages', () => {
        const trace = makeTrace([], {
            traceName: 'LangGraph',
            inputState: {
                messages: [
                    { type: 'system', content: 'system prompt' },
                    { type: 'human', content: 'Hello, I need an export of subscribed users.' },
                ],
            },
        })
        expect(resolveSessionTitle(trace)).toBe('Hello, I need an export of subscribed users.')
    })

    it('falls back to first event $ai_input_state.messages when trace.inputState is null', () => {
        const trace = makeTrace(
            [
                makeEvent('e1', '$ai_span', '2026-05-29T00:00:00.000Z', {
                    $ai_input_state: {
                        messages: [{ role: 'user', content: 'first user message via span' }],
                    },
                }),
            ],
            { traceName: 'LangGraph', inputState: null }
        )
        expect(resolveSessionTitle(trace)).toBe('first user message via span')
    })

    it('falls back to first generation $ai_input when no input_state is present', () => {
        const trace = makeTrace(
            [
                makeEvent('s1', '$ai_span', '2026-05-29T00:00:00.000Z', {}),
                makeEvent('g1', '$ai_generation', '2026-05-29T00:00:01.000Z', {
                    $ai_input: [
                        { role: 'system', content: 'sys' },
                        { role: 'user', content: 'message from $ai_input' },
                    ],
                }),
            ],
            { traceName: 'LangGraph' }
        )
        expect(resolveSessionTitle(trace)).toBe('message from $ai_input')
    })

    it('uses $mcp_intent when no chat messages are present', () => {
        const trace = makeTrace(
            [
                makeEvent('s1', '$ai_span', '2026-05-29T00:00:00.000Z', {
                    $mcp_intent: 'Switching PostHog context to Staging project before creating the experiment.',
                }),
            ],
            { traceName: 'switch-project' }
        )
        expect(resolveSessionTitle(trace)).toBe(
            'Switching PostHog context to Staging project before creating the experiment.'
        )
    })

    it('falls back to traceName when it is not a generic framework name', () => {
        const trace = makeTrace([makeEvent('s1', '$ai_span', '2026-05-29T00:00:00.000Z', {})], {
            traceName: 'switch-project',
        })
        expect(resolveSessionTitle(trace)).toBe('switch-project')
    })

    it.each([['LangGraph'], ['RunnableSequence'], ['ChatPromptTemplate'], ['langgraph']])(
        'rejects generic traceName %p as a title (returns null when no other signal)',
        (name) => {
            const trace = makeTrace([], { traceName: name })
            expect(resolveSessionTitle(trace)).toBeNull()
        }
    )

    it('picks the first event by timestamp, not array order', () => {
        const trace = makeTrace(
            [
                makeEvent('later', '$ai_span', '2026-05-29T00:00:05.000Z', {
                    $ai_input_state: { messages: [{ role: 'user', content: 'later span' }] },
                }),
                makeEvent('earlier', '$ai_span', '2026-05-29T00:00:00.000Z', {
                    $ai_input_state: { messages: [{ role: 'user', content: 'earlier span' }] },
                }),
            ],
            { traceName: 'LangGraph' }
        )
        expect(resolveSessionTitle(trace)).toBe('earlier span')
    })

    it.each([
        {
            desc: 'collapses whitespace',
            messages: [{ role: 'user', content: 'multi\nline\n\nmessage   with   spaces' }],
            expected: 'multi line message with spaces',
        },
        {
            desc: 'does not truncate short titles',
            messages: [{ role: 'user', content: 'short message' }],
            expected: 'short message',
        },
        {
            desc: 'extracts text from array-shaped content (Anthropic typed parts)',
            messages: [
                {
                    role: 'user',
                    content: [
                        { type: 'text', text: 'Look at this image' },
                        { type: 'image', url: 'https://example.com/a.png' },
                    ],
                },
            ],
            expected: 'Look at this image',
        },
        {
            desc: 'skips messages with empty content and uses the next user message',
            messages: [
                { role: 'user', content: '' },
                { role: 'user', content: 'actual question' },
            ],
            expected: 'actual question',
        },
    ])('extracts title content: $desc', ({ messages, expected }) => {
        const trace = makeTrace([], { inputState: { messages } })
        expect(resolveSessionTitle(trace)).toBe(expected)
    })

    it.each([
        {
            desc: 'truncates long titles at a word boundary with an ellipsis',
            content:
                "We've just released SpicyCam - I want to know what the initial user engagement and intent is like - are the users enjoying the new feature?",
            maxLength: undefined,
            maxOut: 121, // 120 + ellipsis
            // Word-boundary backoff: should not include the mid-word fragment "enjoyi".
            notContain: 'enjoyi…',
        },
        {
            desc: 'accepts a custom maxLength',
            content: 'this is a moderately long sentence that should be cut',
            maxLength: 20,
            maxOut: 21,
        },
    ])('$desc', ({ content, maxLength, maxOut, notContain }) => {
        const trace = makeTrace([], { inputState: { messages: [{ role: 'user', content }] } })
        const result = maxLength === undefined ? resolveSessionTitle(trace) : resolveSessionTitle(trace, maxLength)
        expect(result).toBeTruthy()
        expect(result!.length).toBeLessThanOrEqual(maxOut)
        expect(result!.endsWith('…')).toBe(true)
        if (notContain) {
            expect(result).not.toContain(notContain)
        }
    })

    it.each([
        { desc: 'a bare-string $ai_input', input: 'how do I add a feature flag?' },
        { desc: 'a role-less message object in $ai_input', input: [{ content: 'how do I add a feature flag?' }] },
    ])('treats role-less generation input as the user prompt: $desc', ({ input }) => {
        const trace = makeTrace([makeEvent('g1', '$ai_generation', '2026-05-29T00:00:00.000Z', { $ai_input: input })], {
            traceName: 'LangGraph',
        })
        expect(resolveSessionTitle(trace)).toBe('how do I add a feature flag?')
    })
})
