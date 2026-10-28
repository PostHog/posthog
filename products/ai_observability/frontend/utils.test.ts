import api from 'lib/api'

import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import { CompatMessage } from './types'
import {
    asString,
    costContextFromProperties,
    costContextFromTrace,
    formatAiErrorForDisplay,
    formatLLMEventTitle,
    formatModelRowLabel,
    getInternalTagName,
    getSessionID,
    getSessionStartTimestamp,
    getSummarizationLookupDateRange,
    queryEvaluationRuns,
    hasCostBreakdown,
    hasStringContentField,
    isEmptyJSONStructure,
    isInternalToolResultUserMessage,
    isInternalTagMessage,
    isTextContentItem,
    isToolResult,
    isToolStepItem,
    looksLikeXml,
    mapEvaluationRunRow,
    parsePartialJSON,
    parseToolArgumentsForDisplay,
    sanitizeTraceUrlSearchParams,
} from './utils'

type EvaluationRunRow = Parameters<typeof mapEvaluationRunRow>[0]

interface EvaluationRunRowOverrides {
    result?: EvaluationRunRow[6]
    applicable?: EvaluationRunRow[8]
    evaluationType?: EvaluationRunRow[9]
    resultType?: EvaluationRunRow[10]
    sentimentLabel?: EvaluationRunRow[11]
    sentimentScore?: EvaluationRunRow[12]
    sessionId?: EvaluationRunRow[13]
    skipped?: EvaluationRunRow[14]
}

function makeEvaluationRunRow({
    result = true,
    applicable = true,
    evaluationType = 'llm_judge',
    resultType = 'boolean',
    sentimentLabel = null,
    sentimentScore = null,
    sessionId = null,
    skipped = null,
}: EvaluationRunRowOverrides = {}): EvaluationRunRow {
    return [
        'run-1',
        '2026-04-10T12:00:00Z',
        'eval-1',
        'Test Eval',
        'gen-1',
        'trace-1',
        result,
        'Looks good',
        applicable,
        evaluationType,
        resultType,
        sentimentLabel,
        sentimentScore,
        sessionId,
        skipped,
    ]
}

describe('mapEvaluationRunRow', () => {
    it.each([0, 0.49, 1])('preserves a System One probability of %s without inventing reasoning', (probability) => {
        const row = makeEvaluationRunRow()
        row[7] = ''
        row[21] = probability
        const run = mapEvaluationRunRow(row)
        expect(run.probability).toBe(probability)
        expect(run.reasoning).toBe('')
    })

    it.each([
        ['["resolved"]', ['resolved']],
        ['[]', []],
        [null, []],
        ['invalid', null],
        ['[1]', null],
    ])('preserves categorical JSON %p without confusing empty and absent results', (raw, expected) => {
        const row = makeEvaluationRunRow({ result: null, resultType: 'categorical' })
        row[18] = raw
        expect(mapEvaluationRunRow(row)).toMatchObject({
            result_type: 'categorical',
            categories: expected,
            result: null,
        })
    })

    it.each([false, 'false'])('keeps an inapplicable categorical result as N/A (%p)', (applicable) => {
        const row = makeEvaluationRunRow({ result: null, resultType: 'categorical', applicable })
        row[18] = null
        expect(mapEvaluationRunRow(row).categories).toBeNull()
    })

    it.each([
        ['a backfilled verdict', '2026-04-11T08:00:00Z', 'backfill-1'],
        ['a verdict written before these properties existed', null, null],
    ])('maps the run time and backfill of %s', (_case, startTime, backfillId) => {
        const row = makeEvaluationRunRow()
        row[18] = null
        row[19] = startTime
        row[20] = backfillId
        expect(mapEvaluationRunRow(row)).toMatchObject({ start_time: startTime, backfill_id: backfillId })
    })

    it.each([0, 0.5, -2, '0', '0.5', '-2'])('keeps numeric score %p and its original bounds', (score) => {
        const row = makeEvaluationRunRow({ result: null, resultType: 'numeric' })
        row[15] = score
        row[16] = -5
        row[17] = 10
        expect(mapEvaluationRunRow(row)).toMatchObject({
            result_type: 'numeric',
            result: null,
            score: Number(score),
            score_min: -5,
            score_max: 10,
        })
    })

    it.each([null, true, false, '', 'true', 'false'])(
        'does not read a numeric score from the boolean result property (%p)',
        (result) => {
            expect(mapEvaluationRunRow(makeEvaluationRunRow({ result, resultType: 'numeric' }))).toMatchObject({
                result: null,
                score: null,
            })
        }
    )

    it('maps sentiment rows without coercing missing boolean results to false', () => {
        const run = mapEvaluationRunRow(
            makeEvaluationRunRow({
                result: null,
                applicable: null,
                evaluationType: 'sentiment',
                resultType: 'sentiment',
                sentimentLabel: 'positive',
                sentimentScore: '0.91',
            })
        )

        expect(run.result).toBeNull()
        expect(run.evaluation_type).toBe('sentiment')
        expect(run.result_type).toBe('sentiment')
        expect(run.sentiment_label).toBe('positive')
        expect(run.sentiment_score).toBe(0.91)
    })

    it('falls back to sentiment result type for older sentiment rows', () => {
        const run = mapEvaluationRunRow(
            makeEvaluationRunRow({
                result: null,
                applicable: null,
                evaluationType: 'sentiment',
                resultType: null,
                sentimentLabel: 'negative',
            })
        )

        expect(run.result_type).toBe('sentiment')
        expect(run.result).toBeNull()
    })

    it('keeps absent boolean results as null instead of false', () => {
        const run = mapEvaluationRunRow(makeEvaluationRunRow({ result: null }))

        expect(run.result).toBeNull()
    })

    // A skip carries result: false when the evaluation disallows N/A, so anything reading the
    // result alone reports a session that was never graded as one that failed.
    it.each([
        [true, true],
        ['true', true],
        [false, false],
        [null, false],
    ])('maps raw skipped %p to %p', (skipped, expected) => {
        const run = mapEvaluationRunRow(makeEvaluationRunRow({ skipped }))
        expect(run.skipped).toBe(expected)
    })

    it.each([true, 'true', 'True', '1'])('maps explicit pass result %p', (result) => {
        expect(mapEvaluationRunRow(makeEvaluationRunRow({ result })).result).toBe(true)
    })

    it.each([false, 'false', 'False', '0'])('maps explicit fail result %p', (result) => {
        expect(mapEvaluationRunRow(makeEvaluationRunRow({ result })).result).toBe(false)
    })

    it('maps explicitly non-applicable rows to null', () => {
        const run = mapEvaluationRunRow(makeEvaluationRunRow({ result: false, applicable: 'false' }))

        expect(run.result).toBeNull()
        expect(run.applicable).toBe(false)
    })
})

describe('getSummarizationLookupDateRange', () => {
    it('brackets the entity timestamp by a day either side', () => {
        expect(getSummarizationLookupDateRange('2026-01-01T00:00:00Z')).toEqual({
            date_from: '2025-12-31T00:00:00.000Z',
            date_to: '2026-01-02T00:00:00.000Z',
        })
    })

    // Without the guard, dayjs anchors on now, so the window never contains an older entity
    // and the endpoint answers 404 instead of falling back to its own default.
    it.each([
        ['missing', undefined],
        ['unparseable', 'not a timestamp'],
    ])('sends no window at all when the timestamp is %s', (_, createdAt) => {
        expect(getSummarizationLookupDateRange(createdAt)).toEqual({})
    })
})

describe('AI observability utils', () => {
    beforeEach(() => {
        console.warn = jest.fn()
    })

    describe('getSessionStartTimestamp', () => {
        it.each([
            ['2024-01-15T12:00:00Z', '2024-01-14T12:00:00Z'],
            ['2024-01-01T00:00:00Z', '2023-12-31T00:00:00Z'],
            ['2024-03-01T06:30:00Z', '2024-02-29T06:30:00Z'],
        ])('subtracts 24 hours from %s to get %s', (input, expected) => {
            expect(getSessionStartTimestamp(input)).toBe(expected)
        })
    })

    describe('sanitizeTraceUrlSearchParams', () => {
        it.each([
            [
                {
                    date_from: '-30d',
                    event: 'event-id',
                    timestamp: '2026-01-29T22:07:59Z',
                    exception_ts: '2026-01-29T22:07:59Z',
                    line: '5',
                    tab: 'conversation',
                    back_to: 'traces',
                    filters: [{ key: '$ai_model', value: ['gpt-4o'] }],
                    search: 'foo',
                },
                {},
                {
                    date_from: '-30d',
                    filters: [{ key: '$ai_model', value: ['gpt-4o'] }],
                    search: 'foo',
                },
            ],
            [
                {
                    date_from: '-30d',
                    event: 'event-id',
                    search: 'foo',
                    back_to: 'generations',
                },
                { removeSearch: true },
                { date_from: '-30d' },
            ],
        ])('removes trace-scoped URL params', (searchParams, options, expected) => {
            expect(sanitizeTraceUrlSearchParams(searchParams, options)).toEqual(expected)
        })
    })

    describe('parsePartialJSON', () => {
        it.each([
            ['full object', '{"key": "value", "n": 42}', { key: 'value', n: 42 }],
            ['full array', '[1, 2, 3]', [1, 2, 3]],
            ['truncated object', '{"key": "value", "long_field": "some te', { key: 'value', long_field: 'some te' }],
            ['truncated nested object', '{"a": {"b": "c", "d": "efg', { a: { b: 'c', d: 'efg' } }],
            ['truncated array', '[1, 2, "hel', [1, 2, 'hel']],
            ['truncated string value', '"hello wor', 'hello wor'],
        ])('%s', (_label, input, expected) => {
            expect(parsePartialJSON(input)).toEqual(expected)
        })

        it('throws on completely invalid input', () => {
            expect(() => parsePartialJSON('not json at all')).toThrow()
        })

        it.each([
            ['bracket-prefixed text', '[Thinking: The user wants to build a todo app.]I will build it'],
            ['bracket-prefixed with tool call', '[Tool Call: lov-write, Input: {"file_path":"src/index.tsx"}]'],
        ])('returns empty array for %s (not actual JSON)', (_label, input) => {
            // These strings start with "[" so they look like JSON arrays,
            // but the partial parser can't extract any valid elements
            const result = parsePartialJSON(input)
            expect(result).toEqual([])
        })
    })

    describe('looksLikeXml', () => {
        it('detects basic XML structures', () => {
            expect(looksLikeXml('<root><child/></root>')).toBe(true)
            expect(looksLikeXml('<?xml version="1.0"?><root></root>')).toBe(true)
            expect(looksLikeXml('<root attr="1">text</root>')).toBe(true)
            expect(looksLikeXml('<self-closing/>')).toBe(true)
        })

        it('returns true for typical HTML snippets (by design)', () => {
            expect(looksLikeXml('<!DOCTYPE html><html><body></body></html>')).toBe(true)
            expect(looksLikeXml('<div class="x">hi</div>')).toBe(true)
        })

        it('returns false for non-XML-like strings', () => {
            expect(looksLikeXml('a < b and c > d')).toBe(false)
            expect(looksLikeXml('plain text')).toBe(false)
            expect(looksLikeXml('{"foo":"bar"}')).toBe(false)
        })
    })

    describe('getInternalTagName / isInternalTagMessage', () => {
        // The shape these tests pin: typed-parts content with a single text item
        // whose entire body is a balanced internal tag wrapper.
        const typedParts = (text: string): CompatMessage['content'] =>
            [{ type: 'text', text }] as unknown as CompatMessage['content']

        it.each<[name: string, body: string, expected: string]>([
            // String content
            ['flat string with system-reminder (kebab)', '<system-reminder>foo</system-reminder>', 'system-reminder'],
            ['flat string with system_reminder (snake)', '<system_reminder>foo</system_reminder>', 'system_reminder'],
            [
                'flat string with system_reminder_message',
                '<system_reminder_message>foo</system_reminder_message>',
                'system_reminder_message',
            ],
            [
                'flat string with attached_context',
                '<attached_context>foo bar baz</attached_context>',
                'attached_context',
            ],
            ['flat string with voice_mode', '<voice_mode>off</voice_mode>', 'voice_mode'],
            [
                'multi-line internal tag body',
                '<system_reminder>\nyou are an agent\nmode: foo\n</system_reminder>',
                'system_reminder',
            ],
            ['leading/trailing whitespace tolerated', '   \n<voice_mode>off</voice_mode>\n  ', 'voice_mode'],
        ])('returns the tag name for: %s', (_, body, expected) => {
            const message: CompatMessage = { role: 'user', content: body }
            expect(getInternalTagName(message)).toBe(expected)
            expect(isInternalTagMessage(message)).toBe(true)
        })

        it('matches the typed-parts shape (single text item)', () => {
            const message: CompatMessage = {
                role: 'user',
                content: typedParts('<system_reminder>be concise</system_reminder>'),
            }
            expect(getInternalTagName(message)).toBe('system_reminder')
        })

        it('matches the {type, content: string} wrapper shape (Vercel SDK legacy)', () => {
            const message: CompatMessage = {
                role: 'user',
                content: {
                    type: 'text',
                    content: '<system-reminder>foo</system-reminder>',
                } as unknown as CompatMessage['content'],
            }
            expect(getInternalTagName(message)).toBe('system-reminder')
        })

        // ---- negative cases: role gate ----

        it('returns undefined for an assistant-role message even with an internal tag wrapper', () => {
            // Models can legitimately emit `<system_reminder>` in their reply. Don't hide.
            const message: CompatMessage = {
                role: 'assistant',
                content: '<system_reminder>foo</system_reminder>',
            }
            expect(getInternalTagName(message)).toBeUndefined()
        })

        it('returns undefined for a system-role message (system messages are filtered upstream anyway)', () => {
            const message: CompatMessage = {
                role: 'system',
                content: '<system_reminder>foo</system_reminder>',
            }
            expect(getInternalTagName(message)).toBeUndefined()
        })

        // ---- negative cases: allowlist gate ----

        it.each<[name: string, body: string]>([
            ['unrelated tag <thinking> — model may emit as visible content', '<thinking>let me think</thinking>'],
            ['unrelated tag <summary>', '<summary>the user wants X</summary>'],
            ['unrelated tag <analysis>', '<analysis>foo</analysis>'],
            ['unrelated tag <reasoning>', '<reasoning>foo</reasoning>'],
            ['unrelated tag <answer>', '<answer>The capital of France is Paris.</answer>'],
            ['unrelated tag not in allowlist', '<useful-context>foo</useful-context>'],
            ['unrelated tag <relevance-scores>', '<relevance-scores>0.9</relevance-scores>'],
            ['generic single-word <task>', '<task>foo</task>'],
            ['HTML structural <pre>', '<pre>code block</pre>'],
            ['HTML structural <code>', '<code>print("hi")</code>'],
        ])('returns undefined for non-allowlisted tag: %s', (_, body) => {
            const message: CompatMessage = { role: 'user', content: body }
            expect(getInternalTagName(message)).toBeUndefined()
            expect(isInternalTagMessage(message)).toBe(false)
        })

        // ---- negative cases: shape gate ----

        it('returns undefined when text content has leading text before the wrapper', () => {
            // User wrote actual text alongside a wrapper-shaped substring. Don't hide.
            const message: CompatMessage = {
                role: 'user',
                content: 'foo <system_reminder>bar</system_reminder>',
            }
            expect(getInternalTagName(message)).toBeUndefined()
        })

        it('returns undefined when text content has trailing text after the wrapper', () => {
            const message: CompatMessage = {
                role: 'user',
                content: '<system_reminder>foo</system_reminder> bar',
            }
            expect(getInternalTagName(message)).toBeUndefined()
        })

        it('returns undefined when content has two sibling wrappers (multi-block, not single)', () => {
            const message: CompatMessage = {
                role: 'user',
                content: '<system_reminder>foo</system_reminder>\n<voice_mode>off</voice_mode>',
            }
            // Conservative — coalescing multi-wrapper bodies is out of scope.
            expect(getInternalTagName(message)).toBeUndefined()
        })

        it('returns undefined for typed-parts with more than one item', () => {
            // Two text items, even if each is itself an internal tag wrapper. The renderer
            // would lose information if we collapsed this; keep it visible.
            const message: CompatMessage = {
                role: 'user',
                content: [
                    { type: 'text', text: '<system_reminder>foo</system_reminder>' },
                    { type: 'text', text: '<voice_mode>off</voice_mode>' },
                ] as unknown as CompatMessage['content'],
            }
            expect(getInternalTagName(message)).toBeUndefined()
        })

        it('returns undefined for typed-parts with a non-text item (image, tool_use, …)', () => {
            const message: CompatMessage = {
                role: 'user',
                content: [{ type: 'image_url', image_url: { url: 'x' } }] as unknown as CompatMessage['content'],
            }
            expect(getInternalTagName(message)).toBeUndefined()
        })

        // ---- negative cases: case-sensitivity + tag-mismatch guards ----

        it('returns undefined for uppercase tag names (internal tags are lowercase by convention)', () => {
            const message: CompatMessage = { role: 'user', content: '<System_Reminder>foo</System_Reminder>' }
            expect(getInternalTagName(message)).toBeUndefined()
        })

        it('returns undefined when open and close tag names differ', () => {
            // Malformed XML — the backref enforces consistency.
            const message: CompatMessage = {
                role: 'user',
                content: '<system_reminder>foo</voice_mode>',
            }
            expect(getInternalTagName(message)).toBeUndefined()
        })

        it('returns undefined for empty content', () => {
            expect(getInternalTagName({ role: 'user', content: '' })).toBeUndefined()
            expect(getInternalTagName({ role: 'user', content: [] })).toBeUndefined()
            expect(getInternalTagName({ role: 'user', content: null as unknown as string })).toBeUndefined()
        })

        it('handles typed-parts content with a multi-line attached_context wrapper', () => {
            const message: CompatMessage = {
                role: 'user',
                content: typedParts('<attached_context>\nfoo\n\nbar: baz\nqux: 123\n</attached_context>'),
            }
            expect(getInternalTagName(message)).toBe('attached_context')
        })
    })

    describe('isToolResult', () => {
        it.each<[name: string, item: unknown]>([
            ['Anthropic typed tool_result', { type: 'tool_result', tool_use_id: 'toolu_1', content: 'ok' }],
            [
                'Vercel SDK tool-result',
                { type: 'tool-result', toolCallId: 'a', toolName: 'search_docs', output: { ok: true } },
            ],
            [
                'OpenAI Responses function_call_output',
                { type: 'function_call_output', call_id: 'c1', output: 'opaque' },
            ],
            [
                'custom {type:"function", tool_name, content}',
                { type: 'function', tool_name: 'lookup', content: 'opaque' },
            ],
        ])('returns true for: %s', (_, item) => {
            expect(isToolResult(item)).toBe(true)
        })

        it.each<[name: string, item: unknown]>([
            ['plain text part', { type: 'text', text: 'hi' }],
            ['Anthropic tool_use (a tool CALL, not a result)', { type: 'tool_use', id: 't1', name: 'x', input: {} }],
            [
                'OpenAI tool CALL with nested function object',
                { type: 'function', function: { name: 'get_weather', arguments: '{}' } },
            ],
            ['Vercel SDK tool-call', { type: 'tool-call', toolCallId: 'a', toolName: 'x', input: {} }],
            ['image part', { type: 'image_url', image_url: { url: 'x' } }],
            ['null', null],
            ['plain string', 'hello'],
            ['function-typed item without tool_name', { type: 'function' }],
        ])('returns false for: %s', (_, item) => {
            expect(isToolResult(item)).toBe(false)
        })
    })

    describe('isInternalToolResultUserMessage', () => {
        it('returns true for a user message whose content is only typed tool_result parts', () => {
            const message: CompatMessage = {
                role: 'user',
                content: [
                    { type: 'tool_result', tool_use_id: 't1', content: 'value-1' },
                    { type: 'tool_result', tool_use_id: 't2', content: 'value-2' },
                ] as unknown as CompatMessage['content'],
            }
            expect(isInternalToolResultUserMessage(message)).toBe(true)
        })

        it('returns true for the custom `{type:"function", tool_name, content}` shape', () => {
            const message: CompatMessage = {
                role: 'user',
                content: [
                    { type: 'function', tool_name: 'lookup', content: 'opaque' },
                ] as unknown as CompatMessage['content'],
            }
            expect(isInternalToolResultUserMessage(message)).toBe(true)
        })

        it('returns false when a tool-result part sits alongside real user text', () => {
            // Hiding would drop the user's prose.
            const message: CompatMessage = {
                role: 'user',
                content: [
                    { type: 'tool_result', tool_use_id: 't1', content: 'value' },
                    { type: 'text', text: 'and please summarize the above' },
                ] as unknown as CompatMessage['content'],
            }
            expect(isInternalToolResultUserMessage(message)).toBe(false)
        })

        it('returns false for an empty content array', () => {
            expect(isInternalToolResultUserMessage({ role: 'user', content: [] })).toBe(false)
        })

        it('returns false for an assistant-role message even if its content is tool-result-shaped', () => {
            const message: CompatMessage = {
                role: 'assistant',
                content: [
                    { type: 'tool_result', tool_use_id: 't1', content: 'value' },
                ] as unknown as CompatMessage['content'],
            }
            expect(isInternalToolResultUserMessage(message)).toBe(false)
        })

        it('returns false for a flat-string user message (text body, not a parts list)', () => {
            expect(isInternalToolResultUserMessage({ role: 'user', content: 'follow-up question' })).toBe(false)
        })
    })

    describe('formatLLMEventTitle', () => {
        it('formats LLMTrace with traceName', () => {
            const trace: LLMTrace = {
                id: 'trace-1',
                createdAt: '2024-01-01T00:00:00Z',
                distinctId: 'user-1',
                traceName: 'My Custom Trace',
                person: {
                    uuid: 'person-1',
                    created_at: '2024-01-01T00:00:00Z',
                    properties: {},
                    distinct_id: 'user-1',
                },
                events: [],
            }
            expect(formatLLMEventTitle(trace)).toBe('My Custom Trace')
        })

        it('formats LLMTrace without traceName', () => {
            const trace: LLMTrace = {
                id: 'trace-1',
                createdAt: '2024-01-01T00:00:00Z',
                distinctId: 'user-1',
                person: {
                    uuid: 'person-1',
                    created_at: '2024-01-01T00:00:00Z',
                    properties: {},
                    distinct_id: 'user-1',
                },
                events: [],
            }
            expect(formatLLMEventTitle(trace)).toBe('Trace')
        })

        describe('$ai_generation events', () => {
            it('formats generation event with span name', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_generation',
                    properties: {
                        $ai_span_name: 'Chat Completion',
                        $ai_model: 'gpt-4',
                        $ai_provider: 'openai',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Chat Completion')
            })

            it('formats generation event with model and provider', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_generation',
                    properties: {
                        $ai_model: 'gpt-4',
                        $ai_provider: 'openai',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('gpt-4 (openai)')
            })

            it('formats generation event with model only', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_generation',
                    properties: {
                        $ai_model: 'gpt-4',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('gpt-4')
            })

            it('formats generation event without model or provider', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_generation',
                    properties: {},
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Generation')
            })
        })

        describe('$ai_embedding events', () => {
            it('formats embedding event with span name', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_embedding',
                    properties: {
                        $ai_span_name: 'Document Embedding',
                        $ai_model: 'text-embedding-3-small',
                        $ai_provider: 'openai',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Document Embedding')
            })

            it('formats embedding event with model and provider', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_embedding',
                    properties: {
                        $ai_model: 'text-embedding-3-small',
                        $ai_provider: 'openai',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('text-embedding-3-small (openai)')
            })

            it('formats embedding event with model only', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_embedding',
                    properties: {
                        $ai_model: 'text-embedding-3-small',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('text-embedding-3-small')
            })

            it('formats embedding event without model or provider', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_embedding',
                    properties: {},
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Embedding')
            })
        })

        describe('$ai_span and other events', () => {
            it('formats span event with span name', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_span',
                    properties: {
                        $ai_span_name: 'Database Query',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Database Query')
            })

            it('formats span event without span name', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_span',
                    properties: {},
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Span')
            })

            it('formats metric event', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_metric',
                    properties: {
                        $ai_span_name: 'Performance Metric',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Performance Metric')
            })

            it('formats feedback event', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: '$ai_feedback',
                    properties: {
                        $ai_span_name: 'User Feedback',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('User Feedback')
            })

            it('formats unknown event type', () => {
                const event: LLMTraceEvent = {
                    id: 'event-1',
                    event: 'custom_event',
                    properties: {
                        $ai_span_name: 'Custom Action',
                    },
                    createdAt: '2024-01-01T00:00:00Z',
                }
                expect(formatLLMEventTitle(event)).toBe('Custom Action')
            })
        })

        describe('non-string properties (untyped property bag)', () => {
            // `$ai_*` title properties are strings by convention, but the event property bag is
            // untyped. A structured value (object/array) or number must never be returned verbatim,
            // or it would be rendered as a raw React child and crash the page (React error #31).
            const cases: Array<[string, string, Record<string, unknown>, string]> = [
                [
                    'generation, object span name, with model',
                    '$ai_generation',
                    { $ai_span_name: {}, $ai_model: 'gpt-4' },
                    'gpt-4',
                ],
                ['generation, object span name, no model', '$ai_generation', { $ai_span_name: {} }, 'Generation'],
                ['generation, object model', '$ai_generation', { $ai_model: {} }, 'Generation'],
                [
                    'generation, object model, with provider',
                    '$ai_generation',
                    { $ai_model: {}, $ai_provider: 'openai' },
                    'Generation (openai)',
                ],
                ['generation, object provider', '$ai_generation', { $ai_model: 'gpt-4', $ai_provider: {} }, 'gpt-4'],
                ['embedding, object span name', '$ai_embedding', { $ai_span_name: {} }, 'Embedding'],
                ['embedding, object model', '$ai_embedding', { $ai_model: {} }, 'Embedding'],
                ['span, object span name', '$ai_span', { $ai_span_name: {} }, 'Span'],
                ['span, array span name', '$ai_span', { $ai_span_name: [] }, 'Span'],
                ['span, numeric span name', '$ai_span', { $ai_span_name: 123 }, 'Span'],
            ]

            it.each(cases)('%s falls back to a string label', (_label, event, properties, expected) => {
                const traceEvent: LLMTraceEvent = {
                    id: 'event-1',
                    event,
                    properties,
                    createdAt: '2024-01-01T00:00:00Z',
                }
                const title = formatLLMEventTitle(traceEvent)
                expect(typeof title).toBe('string')
                expect(title).toBe(expected)
            })
        })
    })

    describe('formatModelRowLabel', () => {
        it('returns null for a trace', () => {
            const trace: LLMTrace = {
                id: 'trace-1',
                createdAt: '2024-01-01T00:00:00Z',
                distinctId: 'user-1',
                person: {
                    uuid: 'person-1',
                    created_at: '2024-01-01T00:00:00Z',
                    properties: {},
                    distinct_id: 'user-1',
                },
                events: [],
            }
            expect(formatModelRowLabel(trace)).toBeNull()
        })

        const cases: Array<[string, string, Record<string, unknown>, string | null]> = [
            // Only generations with a span name get a model row; otherwise the event title covers it.
            ['span event', '$ai_span', { $ai_span_name: 'My Span', $ai_model: 'gpt-4' }, null],
            ['embedding event', '$ai_embedding', { $ai_span_name: 'Embed', $ai_model: 'gpt-4' }, null],
            ['generation without span name', '$ai_generation', { $ai_model: 'gpt-4' }, null],
            ['generation with object span name', '$ai_generation', { $ai_span_name: {}, $ai_model: 'gpt-4' }, null],
            [
                'generation with model and provider',
                '$ai_generation',
                { $ai_span_name: 'Chat', $ai_model: 'gpt-4', $ai_provider: 'openai' },
                'gpt-4 (openai)',
            ],
            ['generation with model only', '$ai_generation', { $ai_span_name: 'Chat', $ai_model: 'gpt-4' }, 'gpt-4'],
            [
                'generation with object model and string provider',
                '$ai_generation',
                { $ai_span_name: 'Chat', $ai_model: {}, $ai_provider: 'openai' },
                'openai',
            ],
            [
                'generation with string model and object provider',
                '$ai_generation',
                { $ai_span_name: 'Chat', $ai_model: 'gpt-4', $ai_provider: {} },
                'gpt-4',
            ],
            ['generation with object model only', '$ai_generation', { $ai_span_name: 'Chat', $ai_model: {} }, null],
            ['generation with array model only', '$ai_generation', { $ai_span_name: 'Chat', $ai_model: [] }, null],
            ['generation with numeric model only', '$ai_generation', { $ai_span_name: 'Chat', $ai_model: 4 }, null],
            ['generation without model or provider', '$ai_generation', { $ai_span_name: 'Chat' }, null],
        ]

        it.each(cases)('%s', (_label, event, properties, expected) => {
            const traceEvent: LLMTraceEvent = {
                id: 'event-1',
                event,
                properties,
                createdAt: '2024-01-01T00:00:00Z',
            }
            expect(formatModelRowLabel(traceEvent)).toBe(expected)
        })
    })

    describe('getSessionID', () => {
        const baseEvent = (overrides: Partial<LLMTraceEvent> = {}): LLMTraceEvent => ({
            id: 'event-id',
            event: '$ai_span',
            properties: {},
            createdAt: '2024-01-01T00:00:00Z',
            ...overrides,
        })

        const baseTrace = (events: LLMTraceEvent[]): LLMTrace => ({
            id: 'trace-id',
            createdAt: '2024-01-01T00:00:00Z',
            distinctId: 'distinct-id',
            person: {
                uuid: 'person-id',
                created_at: '2024-01-01T00:00:00Z',
                properties: {},
                distinct_id: 'distinct-id',
            },
            events,
        })

        it('returns the direct session id when the event has one', () => {
            const event = baseEvent({
                properties: {
                    $session_id: 'session-123',
                },
            })

            expect(getSessionID(event)).toEqual('session-123')
        })

        it('derives session id from children when $ai_trace lacks direct value', () => {
            const traceEvent = baseEvent({
                id: 'trace-event',
                event: '$ai_trace',
                properties: {},
            })
            const childEvents = [
                baseEvent({
                    id: 'child-1',
                    properties: { $session_id: 'session-abc' },
                }),
                baseEvent({
                    id: 'child-2',
                    properties: { $session_id: 'session-abc' },
                }),
            ]

            expect(getSessionID(traceEvent, childEvents)).toEqual('session-abc')
        })

        it('returns null when child session ids conflict', () => {
            const traceEvent = baseEvent({
                id: 'trace-event',
                event: '$ai_trace',
            })
            const childEvents = [
                baseEvent({
                    id: 'child-1',
                    properties: { $session_id: 'session-abc' },
                }),
                baseEvent({
                    id: 'child-2',
                    properties: { $session_id: 'session-def' },
                }),
            ]

            expect(getSessionID(traceEvent, childEvents)).toBeNull()
        })

        it('uses consistent child session id for pseudo traces', () => {
            const childEvents = [
                baseEvent({ id: 'child-1', properties: { $session_id: 'session-xyz' } }),
                baseEvent({ id: 'child-2', properties: { $session_id: 'session-xyz' } }),
            ]
            const trace = baseTrace(childEvents)

            expect(getSessionID(trace)).toEqual('session-xyz')
        })

        it('returns null for pseudo traces with mixed session ids', () => {
            const childEvents = [
                baseEvent({ id: 'child-1', properties: { $session_id: 'session-xyz' } }),
                baseEvent({ id: 'child-2', properties: { $session_id: 'session-abc' } }),
            ]
            const trace = baseTrace(childEvents)

            expect(getSessionID(trace)).toBeNull()
        })
    })

    describe('costContextFromProperties', () => {
        it('returns undefined when $ai_total_cost_usd is absent', () => {
            expect(costContextFromProperties({})).toBeUndefined()
        })

        it('returns undefined when $ai_total_cost_usd is not a number', () => {
            expect(costContextFromProperties({ $ai_total_cost_usd: 'invalid' })).toBeUndefined()
        })

        it('maps all cost properties', () => {
            const props = {
                $ai_input_cost_usd: 0.01,
                $ai_output_cost_usd: 0.02,
                $ai_request_cost_usd: 0.003,
                $ai_web_search_cost_usd: 0.015,
                $ai_total_cost_usd: 0.048,
            }
            expect(costContextFromProperties(props)).toEqual({
                inputCost: 0.01,
                outputCost: 0.02,
                requestCost: 0.003,
                webSearchCost: 0.015,
                totalCost: 0.048,
            })
        })

        it('leaves optional cost fields as undefined when absent', () => {
            const props = { $ai_total_cost_usd: 0.05 }
            const ctx = costContextFromProperties(props)
            expect(ctx).not.toBeUndefined()
            expect(ctx && ctx.totalCost).toBe(0.05)
            expect(ctx && ctx.inputCost).toBeUndefined()
            expect(ctx && ctx.outputCost).toBeUndefined()
            expect(ctx && ctx.requestCost).toBeUndefined()
            expect(ctx && ctx.webSearchCost).toBeUndefined()
        })
    })

    describe('costContextFromTrace', () => {
        it('returns undefined when totalCost is undefined', () => {
            expect(costContextFromTrace({})).toBeUndefined()
        })

        it('maps all trace cost fields', () => {
            const trace = {
                inputCost: 0.01,
                outputCost: 0.02,
                requestCost: 0.003,
                webSearchCost: 0.015,
                totalCost: 0.048,
            }
            expect(costContextFromTrace(trace)).toEqual({
                inputCost: 0.01,
                outputCost: 0.02,
                requestCost: 0.003,
                webSearchCost: 0.015,
                totalCost: 0.048,
            })
        })

        it('handles trace with only totalCost', () => {
            const trace = { totalCost: 0.05 }
            const ctx = costContextFromTrace(trace)
            expect(ctx).not.toBeUndefined()
            expect(ctx && ctx.totalCost).toBe(0.05)
            expect(ctx && ctx.inputCost).toBeUndefined()
        })
    })

    describe('hasCostBreakdown', () => {
        it('returns false when only totalCost is set', () => {
            expect(hasCostBreakdown({ totalCost: 0.05 })).toBe(false)
        })

        it('returns true when inputCost is present', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, inputCost: 0.01 })).toBe(true)
        })

        it('returns true when outputCost is present', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, outputCost: 0.02 })).toBe(true)
        })

        it('returns true when requestCost is positive', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, requestCost: 0.003 })).toBe(true)
        })

        it('returns false when requestCost is zero', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, requestCost: 0 })).toBe(false)
        })

        it('returns true when webSearchCost is positive', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, webSearchCost: 0.01 })).toBe(true)
        })

        it('returns false when webSearchCost is zero', () => {
            expect(hasCostBreakdown({ totalCost: 0.05, webSearchCost: 0 })).toBe(false)
        })

        it('returns true when inputCost is zero (zero is still a valid breakdown)', () => {
            expect(hasCostBreakdown({ totalCost: 0, inputCost: 0 })).toBe(true)
        })
    })

    describe('isEmptyJSONStructure', () => {
        it.each<[string, unknown, boolean]>([
            ['empty object', {}, true],
            ['empty array', [], true],
            ['non-empty object', { a: 1 }, false],
            ['non-empty array', [1], false],
            ['string', 'hi', false],
            ['number', 0, false],
            ['null', null, false],
            ['undefined', undefined, false],
        ])('returns %s -> %s', (_label, value, expected) => {
            expect(isEmptyJSONStructure(value)).toBe(expected)
        })
    })

    describe('parseToolArgumentsForDisplay', () => {
        it('returns empty for null, undefined, and empty string', () => {
            expect(parseToolArgumentsForDisplay(null)).toEqual({ kind: 'empty' })
            expect(parseToolArgumentsForDisplay(undefined)).toEqual({ kind: 'empty' })
            expect(parseToolArgumentsForDisplay('')).toEqual({ kind: 'empty' })
        })

        it('returns empty for empty object and empty array (object form)', () => {
            expect(parseToolArgumentsForDisplay({})).toEqual({ kind: 'empty' })
            expect(parseToolArgumentsForDisplay([])).toEqual({ kind: 'empty' })
        })

        it('returns empty for stringified empty object/array', () => {
            expect(parseToolArgumentsForDisplay('{}')).toEqual({ kind: 'empty' })
            expect(parseToolArgumentsForDisplay('[]')).toEqual({ kind: 'empty' })
        })

        it('returns parsed object for an object input', () => {
            expect(parseToolArgumentsForDisplay({ location: 'SF' })).toEqual({
                kind: 'parsed',
                value: { location: 'SF' },
            })
        })

        it('returns parsed object for stringified JSON object', () => {
            expect(parseToolArgumentsForDisplay('{"location": "Berlin"}')).toEqual({
                kind: 'parsed',
                value: { location: 'Berlin' },
            })
        })

        it('returns raw string when JSON is unparseable', () => {
            expect(parseToolArgumentsForDisplay('{not valid json')).toEqual({
                kind: 'raw',
                value: '{not valid json',
            })
        })

        it('returns raw string when stringified value parses to a non-object scalar', () => {
            // partial-json may parse `"hello"` to the string "hello" — that's not a structured arg payload, fall back.
            expect(parseToolArgumentsForDisplay('"hello"')).toEqual({ kind: 'raw', value: '"hello"' })
        })
    })

    describe('hasStringContentField', () => {
        it.each<[name: string, input: unknown, expected: boolean]>([
            ['accepts {content: "hi"}', { content: 'hi' }, true],
            ['accepts {type: "text", content: "hi"} — extra fields are fine', { type: 'text', content: 'hi' }, true],
            ['accepts {content: ""} — empty string still passes', { content: '' }, true],
            ['rejects {content: 42} — non-string content', { content: 42 }, false],
            ['rejects {content: null}', { content: null }, false],
            ['rejects missing `content` property', { type: 'text' }, false],
            ['rejects null', null, false],
            ['rejects undefined', undefined, false],
            ['rejects a plain string', 'hi', false],
            ['rejects an array', [{ content: 'hi' }], false],
        ])('%s', (_, input, expected) => {
            expect(hasStringContentField(input)).toBe(expected)
        })
    })

    describe('isToolStepItem', () => {
        it.each<[name: string, input: unknown, expected: boolean]>([
            ['accepts Anthropic `tool_use`', { type: 'tool_use', id: 'toolu_1', name: 'x', input: {} }, true],
            ['accepts Vercel SDK `tool-call`', { type: 'tool-call', toolCallId: 'a', toolName: 'x', input: {} }, true],
            ['accepts unified `{type: "function"}`', { type: 'function', function: { name: 'x' } }, true],
            [
                'accepts OpenAI Responses `function_call`',
                { type: 'function_call', call_id: 'c1', name: 'x', arguments: '{}' },
                true,
            ],
            [
                'accepts OpenAI Responses built-in tool call (e.g. web_search_call)',
                { id: 'ws1', type: 'web_search_call', status: 'completed' },
                true,
            ],
            ['accepts Anthropic `tool_result`', { type: 'tool_result', tool_use_id: 'toolu_1', content: 'ok' }, true],
            [
                'accepts Vercel SDK `tool-result`',
                { type: 'tool-result', toolCallId: 'a', toolName: 'search_docs', result: 'ok' },
                true,
            ],
            ['rejects text content items', { type: 'text', text: 'hi' }, false],
            ['rejects image items', { type: 'image_url', image_url: { url: 'x' } }, false],
            ['rejects file items', { type: 'file', file: { filename: 'f', file_data: 'd' } }, false],
            ['rejects null', null, false],
            ['rejects a plain string', 'function', false],
            ['rejects `{type: "function"}` without a `function` payload', { type: 'function' }, false],
            [
                'rejects `{type: "function", function: "not-an-object"}`',
                { type: 'function', function: 'not-an-object' },
                false,
            ],
        ])('%s', (_, input, expected) => {
            expect(isToolStepItem(input)).toBe(expected)
        })
    })

    describe('isTextContentItem', () => {
        it.each<[name: string, input: unknown, expected: boolean]>([
            ['accepts {type: "text", text: "hi"}', { type: 'text', text: 'hi' }, true],
            ['accepts {type: "text", text: ""}', { type: 'text', text: '' }, true],
            ['rejects missing `text` property', { type: 'text' }, false],
            ['rejects wrong `type` literal', { type: 'image', text: 'hi' }, false],
            ['rejects null', null, false],
            ['rejects undefined', undefined, false],
            ['rejects a plain string', 'hi', false],
            ['rejects an array', [{ type: 'text', text: 'hi' }], false],
        ])('%s', (_, input, expected) => {
            expect(isTextContentItem(input)).toBe(expected)
        })
    })

    describe('asString', () => {
        it.each<[name: string, input: unknown, expected: string | undefined]>([
            ['returns a non-empty string unchanged', 'hello', 'hello'],
            ['returns an empty string as itself (caller decides via `||`)', '', ''],
            ['returns undefined for undefined', undefined, undefined],
            ['returns undefined for null', null, undefined],
            ['returns undefined for a number', 42, undefined],
            ['returns undefined for a boolean', true, undefined],
            ['returns undefined for an object', { value: 'oops' }, undefined],
            ['returns undefined for an array', ['oops'], undefined],
        ])('%s', (_, input, expected) => {
            expect(asString(input)).toBe(expected)
        })
    })

    describe('formatAiErrorForDisplay', () => {
        it.each<[string, unknown, string]>([
            ['string passes through', 'rate limit exceeded', 'rate limit exceeded'],
            ['empty string falls back to Unknown error', '', 'Unknown error'],
            ['null falls back to Unknown error', null, 'Unknown error'],
            ['undefined falls back to Unknown error', undefined, 'Unknown error'],
            [
                'plain object is JSON-stringified',
                { message: 'boom', name: 'Error' },
                '{"message":"boom","name":"Error"}',
            ],
            ['array is JSON-stringified', ['a', 'b'], '["a","b"]'],
            ['number is JSON-stringified', 500, '500'],
            ['boolean is JSON-stringified', true, 'true'],
        ])('%s', (_, input, expected) => {
            expect(formatAiErrorForDisplay(input)).toBe(expected)
        })

        it('falls back to String() when JSON.stringify throws (e.g. circular refs)', () => {
            const circular: Record<string, unknown> = {}
            circular.self = circular
            // JSON.stringify throws on circular refs; helper should fall back to String() and not throw.
            expect(() => formatAiErrorForDisplay(circular)).not.toThrow()
            expect(formatAiErrorForDisplay(circular)).toBe('[object Object]')
        })
    })

    // Regressions found by sampling real production payloads across teams. These
    // shapes were mishandled at some point by the recipe pipeline.
    // Structured content the recipe pipeline surfaces as canonical messages.
})

describe('queryEvaluationRuns', () => {
    const queryHogQL = jest.spyOn(api, 'queryHogQL').mockResolvedValue({ results: [] } as any)

    afterEach(() => queryHogQL.mockClear())

    it('narrows to one backfill as SQL rather than as a string', async () => {
        await queryEvaluationRuns({ evaluationId: 'eval-1', backfillId: 'run-1' })

        // A nested hogql template would arrive escaped as a value and fail to parse, so assert
        // the clause reached the query as SQL.
        expect(queryHogQL.mock.calls[0][0]).toContain("AND properties.$ai_evaluation_backfill_id = 'run-1'")
    })

    it('leaves the runs unfiltered when no backfill is given', async () => {
        await queryEvaluationRuns({ evaluationId: 'eval-1' })

        expect(queryHogQL.mock.calls[0][0]).not.toContain('AND properties.$ai_evaluation_backfill_id =')
        expect(queryHogQL.mock.calls[0][0]).toContain('properties.$ai_evaluation_numeric_result as score')
        expect(queryHogQL.mock.calls[0][0]).toContain('properties.$ai_evaluation_numeric_result_min as score_min')
        expect(queryHogQL.mock.calls[0][0]).toContain('properties.$ai_evaluation_numeric_result_max as score_max')
    })
})
