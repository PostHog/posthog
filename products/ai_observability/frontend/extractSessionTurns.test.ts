import { LLMTrace, LLMTraceEvent } from '~/queries/schema/schema-general'

import {
    buildInputSourceIndices,
    extractSessionTurns,
    pickUserVisibleTurn,
    SessionTurnError,
} from './extractSessionTurns'

function makeGeneration(
    id: string,
    createdAt: string,
    overrides: Partial<LLMTraceEvent['properties']> = {}
): LLMTraceEvent {
    return {
        id,
        event: '$ai_generation',
        createdAt,
        properties: {
            $ai_input: [{ role: 'user', content: 'hi' }],
            $ai_output_choices: [{ role: 'assistant', content: 'hello' }],
            ...overrides,
        },
    }
}

function makeTrace(id: string, events: LLMTraceEvent[], overrides: Partial<LLMTrace> = {}): LLMTrace {
    return {
        id,
        createdAt: events[0]?.createdAt ?? '2026-05-11T00:00:00.000Z',
        distinctId: 'user-1',
        events,
        ...overrides,
    }
}

describe('pickUserVisibleTurn', () => {
    it('returns undefined when the trace has no generation events', () => {
        const trace = makeTrace('t1', [
            { id: 's1', event: '$ai_span', createdAt: '2026-05-11T00:00:00.000Z', properties: {} },
        ])
        expect(pickUserVisibleTurn(trace)).toBeUndefined()
    })

    it('returns the latest $ai_generation by createdAt', () => {
        const g1 = makeGeneration('g1', '2026-05-11T00:00:00.000Z')
        const g2 = makeGeneration('g2', '2026-05-11T00:00:01.000Z')
        const g3 = makeGeneration('g3', '2026-05-11T00:00:02.000Z')
        // Events out of order in the array shouldn't change the answer.
        const trace = makeTrace('t1', [g2, g3, g1])
        expect(pickUserVisibleTurn(trace)?.id).toBe('g3')
    })

    it('ignores non-generation events even if they are newer', () => {
        const g1 = makeGeneration('g1', '2026-05-11T00:00:00.000Z')
        const traceEvent: LLMTraceEvent = {
            id: 'trace',
            event: '$ai_trace',
            createdAt: '2026-05-11T00:00:09.000Z',
            properties: {},
        }
        const trace = makeTrace('t1', [g1, traceEvent])
        expect(pickUserVisibleTurn(trace)?.id).toBe('g1')
    })
})

describe('buildInputSourceIndices', () => {
    it('returns an empty array for non-array inputs', () => {
        expect(buildInputSourceIndices('not an array', undefined)).toEqual([])
    })

    it('prepends -1 when tools are present', () => {
        const indices = buildInputSourceIndices([{ role: 'user', content: 'hi' }], [{ name: 'lookup' }])
        expect(indices[0]).toBe(-1)
    })

    it('emits one index per normalized message, repeating when one raw entry expands', () => {
        // A single raw entry with typed parts may normalize to multiple CompatMessages.
        const raw = [
            { role: 'user', content: 'Hi' },
            {
                role: 'assistant',
                content: [
                    { type: 'thinking', thinking: 'pondering' },
                    { type: 'text', text: 'Hello' },
                ],
            },
        ]
        const indices = buildInputSourceIndices(raw, undefined)
        // First entry maps to 0; second entry expands to 2 messages, both mapping to 1.
        expect(indices[0]).toBe(0)
        // We don't assert on the rest of the shape — `normalizeMessage`'s expansion is
        // covered by utils.test.ts — but every emitted index should be in {0, 1}.
        for (const i of indices) {
            expect([0, 1]).toContain(i)
        }
    })
})

describe('extractSessionTurns — cross-trace dedup', () => {
    it('returns isLoaded=false placeholders for traces whose full data is missing', () => {
        const t1 = makeTrace('t1', [makeGeneration('g1', '2026-05-11T00:00:00.000Z')])
        const turns = extractSessionTurns([t1], {})
        expect(turns).toHaveLength(1)
        expect(turns[0].isLoaded).toBe(false)
        expect(turns[0].newInputs).toEqual([])
        expect(turns[0].outputs).toEqual([])
        expect(turns[0].tools).toEqual([])
        expect(turns[0].errors).toEqual([])
    })

    it('returns an isLoaded turn with no userVisibleTurn for span-only traces', () => {
        // No $ai_generation in the trace — `pickUserVisibleTurn` finds nothing,
        // so the placeholder turn signals "loaded, but no conversational content
        // to render". `TurnBody` renders the "No conversational turn to render"
        // message in this state.
        const t1 = makeTrace('t1', [
            { id: 's1', event: '$ai_span', createdAt: '2026-05-11T00:00:00.000Z', properties: {} },
        ])
        const turns = extractSessionTurns([t1], { t1 })
        expect(turns).toHaveLength(1)
        expect(turns[0].isLoaded).toBe(true)
        expect(turns[0].userVisibleTurn).toBeUndefined()
        expect(turns[0].newInputs).toEqual([])
        expect(turns[0].outputs).toEqual([])
    })

    it('shows the full input on the first turn (nothing seen yet)', () => {
        const t1 = makeTrace('t1', [
            makeGeneration('g1', '2026-05-11T00:00:00.000Z', {
                $ai_input: [{ role: 'user', content: 'Hi! Can you help me plan a trip to Japan?' }],
                $ai_output_choices: [{ role: 'assistant', content: 'Of course! What time of year?' }],
            }),
        ])
        const turns = extractSessionTurns([t1], { t1 })
        expect(turns[0].isLoaded).toBe(true)
        expect(turns[0].newInputs).toHaveLength(1)
        expect(turns[0].newInputs[0].content).toBe('Hi! Can you help me plan a trip to Japan?')
        expect(turns[0].outputs).toHaveLength(1)
    })

    it('hides messages already shown in earlier turns', () => {
        // Turn 1 sends: [user: "Hi"]   →   assistant: "Hello"
        // Turn 2 sends: [user: "Hi", assistant: "Hello", user: "Tell me a joke"]
        //   Without dedup we would re-render the first two; with dedup, only the new user message.
        const t1 = makeTrace('t1', [
            makeGeneration('g1', '2026-05-11T00:00:00.000Z', {
                $ai_input: [{ role: 'user', content: 'Hi' }],
                $ai_output_choices: [{ role: 'assistant', content: 'Hello' }],
            }),
        ])
        const t2 = makeTrace('t2', [
            makeGeneration('g2', '2026-05-11T00:00:01.000Z', {
                $ai_input: [
                    { role: 'user', content: 'Hi' },
                    { role: 'assistant', content: 'Hello' },
                    { role: 'user', content: 'Tell me a joke' },
                ],
                $ai_output_choices: [{ role: 'assistant', content: 'Why did the chicken...' }],
            }),
        ])
        const turns = extractSessionTurns([t1, t2], { t1, t2 })
        expect(turns[1].newInputs).toHaveLength(1)
        expect(turns[1].newInputs[0].content).toBe('Tell me a joke')
        // The output is rendered in full — it's new this turn.
        expect(turns[1].outputs).toHaveLength(1)
        expect(turns[1].outputs[0].content).toBe('Why did the chicken...')
    })

    it('renders identical messages within the same turn (count-based dedup)', () => {
        // Dedup tracks how many copies of each signature have been shown so far,
        // not just whether the signature has been seen. Within-turn duplicates
        // are real content (the trace shows the agent saw both) and render as
        // separate bubbles — hiding one would silently drop information from the
        // transcript. Prior behavior collapsed within-turn duplicates as a side
        // effect of set-based dedup; the count-based model unifies cross-turn
        // and within-turn handling so legitimate repeats always survive.
        const t1 = makeTrace('t1', [
            makeGeneration('g1', '2026-05-11T00:00:00.000Z', {
                $ai_input: [
                    { role: 'tool', content: 'Memory appended.' },
                    { role: 'tool', content: 'Memory appended.' },
                    { role: 'user', content: 'Continue' },
                ],
                $ai_output_choices: [{ role: 'assistant', content: 'ok' }],
            }),
        ])
        const turns = extractSessionTurns([t1], { t1 })
        expect(turns[0].newInputs.map((m) => m.role)).toEqual(['tool', 'tool', 'user'])
    })

    it('renders a repeated user message that arrives after the assistant replied to its first occurrence', () => {
        // Radu's review case: the user typed "continue" twice, with an
        // assistant reply in between. Turn 2's $ai_input carries the full
        // running history — [continue, sure, continue] — and the second
        // "continue" must render despite signature-matching the first.
        // Set-based dedup would silently drop it, leaving the transcript
        // appearing to skip a real user turn.
        const t1 = makeTrace('t1', [
            makeGeneration('g1', '2026-05-11T00:00:00.000Z', {
                $ai_input: [{ role: 'user', content: 'continue' }],
                $ai_output_choices: [{ role: 'assistant', content: 'sure' }],
            }),
        ])
        const t2 = makeTrace('t2', [
            makeGeneration('g2', '2026-05-11T00:00:01.000Z', {
                $ai_input: [
                    { role: 'user', content: 'continue' },
                    { role: 'assistant', content: 'sure' },
                    { role: 'user', content: 'continue' },
                ],
                $ai_output_choices: [{ role: 'assistant', content: 'ok' }],
            }),
        ])
        const turns = extractSessionTurns([t1, t2], { t1, t2 })
        expect(turns[1].newInputs).toHaveLength(1)
        expect(turns[1].newInputs[0].role).toBe('user')
        expect(turns[1].newInputs[0].content).toBe('continue')
    })

    it('renders the same user message N times when it appears N times across N turns', () => {
        // Generalisation of the "continue" case: the user keeps asking the
        // exact same thing across three turns. Each turn's $ai_input adds one
        // more copy on top of the prior history; the count-based dedup
        // surfaces exactly the one new copy per turn.
        const make = (index: number, inputs: { role: string; content: string }[]): LLMTrace =>
            makeTrace(`t${index}`, [
                makeGeneration(`g${index}`, `2026-05-11T00:00:0${index - 1}.000Z`, {
                    $ai_input: inputs,
                    $ai_output_choices: [{ role: 'assistant', content: `reply ${index}` }],
                }),
            ])
        const t1 = make(1, [{ role: 'user', content: 'same?' }])
        const t2 = make(2, [
            { role: 'user', content: 'same?' },
            { role: 'assistant', content: 'reply 1' },
            { role: 'user', content: 'same?' },
        ])
        const t3 = make(3, [
            { role: 'user', content: 'same?' },
            { role: 'assistant', content: 'reply 1' },
            { role: 'user', content: 'same?' },
            { role: 'assistant', content: 'reply 2' },
            { role: 'user', content: 'same?' },
        ])
        const turns = extractSessionTurns([t1, t2, t3], { t1, t2, t3 })
        // Each turn surfaces exactly the one new user message.
        expect(turns[0].newInputs.map((m) => m.content)).toEqual(['same?'])
        expect(turns[1].newInputs.map((m) => m.content)).toEqual(['same?'])
        expect(turns[2].newInputs.map((m) => m.content)).toEqual(['same?'])
    })

    it('renders only the delta when a later turn carries more copies than were shown', () => {
        // Asymmetric counts: turn 1 had two copies of the same tool response
        // (both rendered under count-based dedup). Turn 2 carries three copies
        // in its running history — the third one is new and must render.
        const t1 = makeTrace('t1', [
            makeGeneration('g1', '2026-05-11T00:00:00.000Z', {
                $ai_input: [
                    { role: 'tool', content: 'ack' },
                    { role: 'tool', content: 'ack' },
                ],
                $ai_output_choices: [{ role: 'assistant', content: 'thanks' }],
            }),
        ])
        const t2 = makeTrace('t2', [
            makeGeneration('g2', '2026-05-11T00:00:01.000Z', {
                $ai_input: [
                    { role: 'tool', content: 'ack' },
                    { role: 'tool', content: 'ack' },
                    { role: 'assistant', content: 'thanks' },
                    { role: 'tool', content: 'ack' },
                ],
                $ai_output_choices: [{ role: 'assistant', content: 'done' }],
            }),
        ])
        const turns = extractSessionTurns([t1, t2], { t1, t2 })
        expect(turns[1].newInputs.map((m) => m.role)).toEqual(['tool'])
    })

    it('renders an assistant reply that exactly repeats a prior turn output', () => {
        // The assistant emits the same reply across two turns (e.g. a curt
        // "done" after similar requests). Each turn's output is a brand-new
        // emission and must render in full, regardless of whether earlier
        // outputs had the same signature.
        const t1 = makeTrace('t1', [
            makeGeneration('g1', '2026-05-11T00:00:00.000Z', {
                $ai_input: [{ role: 'user', content: 'first' }],
                $ai_output_choices: [{ role: 'assistant', content: 'done' }],
            }),
        ])
        const t2 = makeTrace('t2', [
            makeGeneration('g2', '2026-05-11T00:00:01.000Z', {
                $ai_input: [
                    { role: 'user', content: 'first' },
                    { role: 'assistant', content: 'done' },
                    { role: 'user', content: 'second' },
                ],
                $ai_output_choices: [{ role: 'assistant', content: 'done' }],
            }),
        ])
        const turns = extractSessionTurns([t1, t2], { t1, t2 })
        // Turn 2 input delta is the new user message; the repeated assistant
        // "done" in the history was already shown as turn 1's output.
        expect(turns[1].newInputs.map((m) => m.content)).toEqual(['second'])
        // Turn 2 output renders in full — outputs are never dedup'd.
        expect(turns[1].outputs.map((m) => m.content)).toEqual(['done'])

        // Now a third turn carries both prior outputs in its history. Each
        // was already accounted for (turn 1's output bumped seen to 1; turn
        // 2's output bumped it to 2), so neither re-renders, and the new
        // user message surfaces alone.
        const t3 = makeTrace('t3', [
            makeGeneration('g3', '2026-05-11T00:00:02.000Z', {
                $ai_input: [
                    { role: 'user', content: 'first' },
                    { role: 'assistant', content: 'done' },
                    { role: 'user', content: 'second' },
                    { role: 'assistant', content: 'done' },
                    { role: 'user', content: 'third' },
                ],
                $ai_output_choices: [{ role: 'assistant', content: 'ok' }],
            }),
        ])
        const turnsAfterT3 = extractSessionTurns([t1, t2, t3], { t1, t2, t3 })
        expect(turnsAfterT3[2].newInputs.map((m) => m.content)).toEqual(['third'])
    })

    it('treats messages with same content but different roles as distinct', () => {
        const t1 = makeTrace('t1', [
            makeGeneration('g1', '2026-05-11T00:00:00.000Z', {
                $ai_input: [{ role: 'user', content: 'ok' }],
                $ai_output_choices: [{ role: 'assistant', content: 'noted' }],
            }),
        ])
        const t2 = makeTrace('t2', [
            makeGeneration('g2', '2026-05-11T00:00:01.000Z', {
                $ai_input: [
                    { role: 'user', content: 'ok' },
                    // Same content as the earlier user message, but different role — must NOT dedup.
                    { role: 'assistant', content: 'ok' },
                ],
                $ai_output_choices: [{ role: 'assistant', content: 'done' }],
            }),
        ])
        const turns = extractSessionTurns([t1, t2], { t1, t2 })
        expect(turns[1].newInputs.map((m) => m.role)).toEqual(['assistant'])
    })

    it('keeps two image+text messages distinct when the images differ', () => {
        // Regression guard: someone stripping attachment data from
        // `messageSignature` thinking it's not needed for identity would
        // collapse these two messages and silently drop the second image.
        const t1 = makeTrace('t1', [
            makeGeneration('g1', '2026-05-11T00:00:00.000Z', {
                $ai_input: [
                    {
                        role: 'user',
                        content: [
                            { type: 'text', text: 'What about this one?' },
                            { type: 'image_url', image_url: { url: 'https://example.com/a.png' } },
                        ],
                    },
                ],
                $ai_output_choices: [{ role: 'assistant', content: 'A cat.' }],
            }),
        ])
        const t2 = makeTrace('t2', [
            makeGeneration('g2', '2026-05-11T00:00:01.000Z', {
                $ai_input: [
                    {
                        role: 'user',
                        content: [
                            { type: 'text', text: 'What about this one?' },
                            { type: 'image_url', image_url: { url: 'https://example.com/a.png' } },
                        ],
                    },
                    { role: 'assistant', content: 'A cat.' },
                    {
                        role: 'user',
                        content: [
                            { type: 'text', text: 'What about this one?' },
                            { type: 'image_url', image_url: { url: 'https://example.com/b.png' } },
                        ],
                    },
                ],
                $ai_output_choices: [{ role: 'assistant', content: 'A dog.' }],
            }),
        ])
        const turns = extractSessionTurns([t1, t2], { t1, t2 })
        expect(turns[1].newInputs).toHaveLength(1)
        expect(turns[1].newInputs[0].role).toBe('user')
    })

    it('dedups an assistant message even when its output shape differs from the next-turn-input shape', () => {
        // SDK pattern observed in the wild: $ai_output_choices comes back as a
        // flat-string OpenAI-style message, but the next call's $ai_input
        // wraps that same assistant reply as Anthropic-style typed parts
        // (e.g. an app stores history as typed parts even though it called
        // OpenAI; OpenAI Responses → Chat Completions migration; LangChain
        // round-tripping). The output's signature in `seenSignatures` is the
        // flat-string form; the next turn's input produces a typed-parts
        // signature. Without convergence in `normalizeMessage`, the assistant
        // message re-renders as new — a silent regression of the kind dedup
        // is supposed to prevent. This test pins that convergence.
        const t1 = makeTrace('t1', [
            makeGeneration('g1', '2026-05-11T00:00:00.000Z', {
                $ai_input: [{ role: 'user', content: 'Hi' }],
                // Flat-string OpenAI Chat Completions output.
                $ai_output_choices: [{ role: 'assistant', content: 'Hello' }],
            }),
        ])
        const t2 = makeTrace('t2', [
            makeGeneration('g2', '2026-05-11T00:00:01.000Z', {
                $ai_input: [
                    { role: 'user', content: 'Hi' },
                    // Same assistant content, but rewrapped as Anthropic-style typed parts.
                    { role: 'assistant', content: [{ type: 'text', text: 'Hello' }] },
                    { role: 'user', content: 'Continue' },
                ],
                $ai_output_choices: [{ role: 'assistant', content: 'Sure!' }],
            }),
        ])
        const turns = extractSessionTurns([t1, t2], { t1, t2 })
        // Only "Continue" should survive — turn 1's flat-string assistant
        // output should match turn 2's typed-parts assistant input.
        expect(turns[1].newInputs.map((m) => m.role)).toEqual(['user'])
        expect(turns[1].newInputs[0].content).toBe('Continue')
    })
})

describe('extractSessionTurns — tools and errors', () => {
    it('dedupes repeated tool names into first-appearance order on the SessionTurn', () => {
        const span = (id: string, name: string): LLMTraceEvent => ({
            id,
            event: '$ai_span',
            createdAt: '2026-05-11T00:00:00.000Z',
            properties: { $ai_span_name: name },
        })
        const t1 = makeTrace('t1', [
            span('s1', 'fetch_user'),
            span('s2', 'subscription_lookup'),
            span('s3', 'fetch_user'), // duplicate — first-appearance order wins
            makeGeneration('g1', '2026-05-11T00:00:01.000Z', {
                // Generation also calls `fetch_user` — must collapse with the spans.
                $ai_output_choices: [
                    {
                        role: 'assistant',
                        content: '',
                        tool_calls: [{ id: 'a', type: 'function', function: { name: 'fetch_user', arguments: '{}' } }],
                    },
                ],
            }),
        ])
        const [turn] = extractSessionTurns([t1], { t1 })
        expect(turn.tools).toEqual(['fetch_user', 'subscription_lookup'])
    })

    it('surfaces the first chronological error with label + message', () => {
        const errorSpan: LLMTraceEvent = {
            id: 's1',
            event: '$ai_span',
            createdAt: '2026-05-11T00:00:01.000Z',
            properties: {
                $ai_span_name: 'subscription_lookup',
                $ai_is_error: 'true',
                $ai_error: { message: '404 not found: subscription does not exist' },
            },
        }
        const t1 = makeTrace('t1', [makeGeneration('g1', '2026-05-11T00:00:00.000Z'), errorSpan])
        const [turn] = extractSessionTurns([t1], { t1 })
        expect(turn.errors).toEqual([
            {
                label: 'subscription_lookup',
                message: '404 not found: subscription does not exist',
            },
        ])
    })

    it('returns errors=[] when no event has an error flag', () => {
        const t1 = makeTrace('t1', [makeGeneration('g1', '2026-05-11T00:00:00.000Z')])
        const [turn] = extractSessionTurns([t1], { t1 })
        expect(turn.errors).toEqual([])
    })

    // Payload-wins rule: a populated `$ai_error` outranks `$ai_is_error: "false"`,
    // and the flag-only path uses strict `=== 'true'` so the string `"false"` doesn't
    // get treated as truthy.
    it.each<[name: string, errorPayload: unknown, expectedErrors: SessionTurnError[]]>([
        ['no $ai_error payload — flag rules, stays non-error', undefined, []],
        [
            '$ai_error populated — payload rules, becomes an error',
            { message: 'connection timeout' },
            [{ label: 'fetch_user', message: 'connection timeout' }],
        ],
    ])('with `$ai_is_error: "false"` and %s', (_, errorPayload, expectedErrors) => {
        const event: LLMTraceEvent = {
            id: 's1',
            event: '$ai_span',
            createdAt: '2026-05-11T00:00:01.000Z',
            properties: {
                $ai_span_name: 'fetch_user',
                $ai_is_error: 'false',
                ...(errorPayload !== undefined ? { $ai_error: errorPayload } : {}),
            },
        }
        const t1 = makeTrace('t1', [makeGeneration('g1', '2026-05-11T00:00:00.000Z'), event])
        const [turn] = extractSessionTurns([t1], { t1 })
        expect(turn.errors).toEqual(expectedErrors)
    })

    it('dedups errors by label + message — retries collapse to one entry', () => {
        // Three retries of the same failure should appear as one entry, not three.
        // `trace.errorCount` (from the summary) keeps the raw event count; `errors.length`
        // reflects the count of DISTINCT failures.
        const errorSpan = (id: string, createdAt: string): LLMTraceEvent => ({
            id,
            event: '$ai_span',
            createdAt,
            properties: {
                $ai_span_name: 'fetch_user',
                $ai_is_error: 'true',
                $ai_error: { message: 'connection timeout' },
            },
        })
        const t1 = makeTrace('t1', [
            errorSpan('s1', '2026-05-11T00:00:00.000Z'),
            errorSpan('s2', '2026-05-11T00:00:01.000Z'),
            errorSpan('s3', '2026-05-11T00:00:02.000Z'),
            makeGeneration('g1', '2026-05-11T00:00:03.000Z'),
        ])
        const [turn] = extractSessionTurns([t1], { t1 })
        expect(turn.errors).toEqual([{ label: 'fetch_user', message: 'connection timeout' }])
    })

    it('preserves distinct errors in chronological first-appearance order', () => {
        // Three different failures appearing in order should all surface — and the
        // order should be chronological (by createdAt), not whatever order the
        // events array happened to come back in.
        const errorEvent = (id: string, createdAt: string, spanName: string, message: string): LLMTraceEvent => ({
            id,
            event: '$ai_span',
            createdAt,
            properties: { $ai_span_name: spanName, $ai_is_error: 'true', $ai_error: { message } },
        })
        const t1 = makeTrace('t1', [
            // Deliberately out of chronological order in the array.
            errorEvent('s3', '2026-05-11T00:00:02.000Z', 'send_email', 'rate limited'),
            errorEvent('s1', '2026-05-11T00:00:00.000Z', 'fetch_user', 'connection timeout'),
            errorEvent('s2', '2026-05-11T00:00:01.000Z', 'subscription_lookup', '404 not found'),
            makeGeneration('g1', '2026-05-11T00:00:03.000Z'),
        ])
        const [turn] = extractSessionTurns([t1], { t1 })
        expect(turn.errors.map((e) => e.label)).toEqual(['fetch_user', 'subscription_lookup', 'send_email'])
    })
})

// Fixtures below mirror the shape of real production payloads — typed parts,
// `cache_control` on text parts, OpenAI `tool_calls` with JSON-string arguments,
// Anthropic `thinking` / `tool_use` / `tool_result` parts — but use neutral
// travel-domain content. The tests below assert only on `role` sequences, so
// content is irrelevant to correctness; what matters is preserving every
// structural feature the dedup signature has to handle.

/** OpenAI Chat Completions multi-turn with `tool_calls` (string args). */
const OPENAI_CHAT_TURN1_INPUT: unknown[] = [
    { role: 'system', content: 'You are a helpful travel assistant.' },
    { role: 'system', content: 'User preferences: metric units.' },
    { role: 'user', content: 'What is the weather like in Berlin this weekend?' },
]
const OPENAI_CHAT_TURN1_OUTPUT: unknown[] = [{ role: 'assistant', content: 'Let me check the forecast for you.' }]
const OPENAI_CHAT_TURN2_INPUT: unknown[] = [
    ...OPENAI_CHAT_TURN1_INPUT,
    ...OPENAI_CHAT_TURN1_OUTPUT,
    {
        role: 'assistant',
        content: 'I should call the weather API.',
        refusal: null,
        tool_calls: [
            {
                function: {
                    // OpenAI emits arguments as a JSON-encoded string, not a parsed object.
                    arguments: '{"city":"Berlin","date":"saturday"}',
                    name: 'get_weather',
                },
                id: 'call_anon_abc123',
                type: 'function',
            },
        ],
    },
    // Tool response in this trace had no `tool_call_id` — observed in real production data.
    { role: 'tool', content: 'Sunny, 22°C.' },
]
const OPENAI_CHAT_TURN2_OUTPUT: unknown[] = [
    { role: 'assistant', content: 'Berlin will be sunny and around 22°C on Saturday.' },
]

/** Anthropic multi-part system prompt with `cache_control` metadata on text parts. */
const ANTHROPIC_CACHE_CONTROL_TURN1_INPUT: unknown[] = [
    {
        role: 'system',
        content: [
            {
                cache_control: { ttl: '1h', type: 'ephemeral' },
                text: 'You are a helpful travel assistant.',
                type: 'text',
            },
        ],
    },
    { role: 'system', content: 'Preferences: metric units.' },
    { role: 'system', content: 'Locale: en-DE.' },
    { role: 'user', content: [{ text: 'Hello.', type: 'text' }] },
    {
        role: 'user',
        content: [
            {
                cache_control: { type: 'ephemeral' },
                text: 'What is the weather in Berlin this weekend?',
                type: 'text',
            },
        ],
    },
]
const ANTHROPIC_CACHE_CONTROL_TURN1_OUTPUT: unknown[] = [
    { role: 'assistant', content: [{ type: 'text', text: 'Let me check the forecast.' }] },
]
const ANTHROPIC_CACHE_CONTROL_TURN2_INPUT: unknown[] = [
    ...ANTHROPIC_CACHE_CONTROL_TURN1_INPUT,
    ...ANTHROPIC_CACHE_CONTROL_TURN1_OUTPUT,
    {
        role: 'user',
        content: [{ cache_control: { type: 'ephemeral' }, text: 'What about Sunday?', type: 'text' }],
    },
]
const ANTHROPIC_CACHE_CONTROL_TURN2_OUTPUT: unknown[] = [
    { role: 'assistant', content: [{ type: 'text', text: 'Sunday will be cloudy.' }] },
]

/** Anthropic with extended-thinking + tool_use + tool_result content parts. */
const ANTHROPIC_TOOL_USE_TURN1_INPUT: unknown[] = [
    { role: 'user', content: 'What is the weather in Berlin?' },
    {
        role: 'assistant',
        content: [
            { signature: 'anon_signature_xyz', thinking: 'I should call the weather tool.', type: 'thinking' },
            {
                caller: { type: 'direct' },
                id: 'toolu_anon01',
                input: { city: 'Berlin' },
                name: 'get_weather',
                type: 'tool_use',
            },
        ],
    },
]
const ANTHROPIC_TOOL_USE_TURN1_OUTPUT: unknown[] = [
    {
        role: 'assistant',
        content: [{ type: 'text', text: 'Berlin is sunny, 22°C. Anything else?' }],
    },
]
const ANTHROPIC_TOOL_USE_TURN2_INPUT: unknown[] = [
    ...ANTHROPIC_TOOL_USE_TURN1_INPUT,
    {
        role: 'user',
        content: [
            {
                content: [{ text: 'Sunny, 22°C.', type: 'text' }],
                tool_use_id: 'toolu_anon01',
                type: 'tool_result',
            },
            { cache_control: { type: 'ephemeral' }, text: 'Thanks.', type: 'text' },
        ],
    },
    ...ANTHROPIC_TOOL_USE_TURN1_OUTPUT,
    { role: 'user', content: 'And in Paris?' },
]
const ANTHROPIC_TOOL_USE_TURN2_OUTPUT: unknown[] = [
    { role: 'assistant', content: [{ type: 'text', text: 'Paris is cloudy, 18°C.' }] },
]

interface RealShapeCase {
    name: string
    turn1Input: unknown[]
    turn1Output: unknown[]
    turn2Input: unknown[]
    turn2Output: unknown[]
    /**
     * Role sequence we expect `normalizeMessages` to emit for the delta in
     * turn 2's input — i.e. the messages we actually want to *render* after
     * hiding everything turn 1 already showed. Pinning roles (not just count)
     * catches content drift: if `normalizeMessage`'s expansion ever changes
     * which parts merge or split, the count could coincidentally stay the
     * same while the rendered conversation silently differs.
     */
    expectedNewInputRolesTurn2: string[]
}

const REAL_SHAPE_CASES: RealShapeCase[] = [
    {
        name: 'OpenAI Chat with tool_calls',
        turn1Input: OPENAI_CHAT_TURN1_INPUT,
        turn1Output: OPENAI_CHAT_TURN1_OUTPUT,
        turn2Input: OPENAI_CHAT_TURN2_INPUT,
        turn2Output: OPENAI_CHAT_TURN2_OUTPUT,
        // Turn 2's delta beyond turn 1: assistant (reasoning + tool_calls) and tool response.
        expectedNewInputRolesTurn2: ['assistant', 'tool'],
    },
    {
        name: 'Anthropic with cache_control typed parts',
        turn1Input: ANTHROPIC_CACHE_CONTROL_TURN1_INPUT,
        turn1Output: ANTHROPIC_CACHE_CONTROL_TURN1_OUTPUT,
        turn2Input: ANTHROPIC_CACHE_CONTROL_TURN2_INPUT,
        turn2Output: ANTHROPIC_CACHE_CONTROL_TURN2_OUTPUT,
        // Turn 2's delta: one new user follow-up message.
        expectedNewInputRolesTurn2: ['user'],
    },
    {
        name: 'Anthropic with thinking + tool_use + tool_result',
        turn1Input: ANTHROPIC_TOOL_USE_TURN1_INPUT,
        turn1Output: ANTHROPIC_TOOL_USE_TURN1_OUTPUT,
        turn2Input: ANTHROPIC_TOOL_USE_TURN2_INPUT,
        turn2Output: ANTHROPIC_TOOL_USE_TURN2_OUTPUT,
        // Turn 2's delta is one Anthropic user-role message with `[tool_result, text]`
        // parts plus a follow-up user message. `normalizeMessage` expands the typed-
        // parts entry into two normalized messages (the tool_result part takes role
        // "assistant (tool result)"; the text part takes role "user"), then the
        // follow-up user message adds a third. Pinning the role sequence catches
        // drift if `normalizeMessage` ever rebalances this split.
        expectedNewInputRolesTurn2: ['assistant (tool result)', 'user', 'user'],
    },
]

describe('extractSessionTurns — real production shapes (anonymized)', () => {
    it.each(REAL_SHAPE_CASES)('first turn renders the full input ($name)', ({ turn1Input, turn1Output }) => {
        const t1 = makeTrace('t1', [
            makeGeneration('g1', '2026-05-11T00:00:00.000Z', {
                $ai_input: turn1Input,
                $ai_output_choices: turn1Output,
            }),
        ])
        const turns = extractSessionTurns([t1], { t1 })
        expect(turns[0].isLoaded).toBe(true)
        // We don't assert an exact count for turn 1 — `normalizeMessages` is the
        // authority on expansion of typed parts. We just confirm it produced
        // *something* renderable.
        expect(turns[0].newInputs.length).toBeGreaterThan(0)
    })

    it.each(REAL_SHAPE_CASES)(
        'second turn hides everything from turn 1 and renders only the delta ($name)',
        ({ turn1Input, turn1Output, turn2Input, turn2Output, expectedNewInputRolesTurn2 }) => {
            const t1 = makeTrace('t1', [
                makeGeneration('g1', '2026-05-11T00:00:00.000Z', {
                    $ai_input: turn1Input,
                    $ai_output_choices: turn1Output,
                }),
            ])
            const t2 = makeTrace('t2', [
                makeGeneration('g2', '2026-05-11T00:00:01.000Z', {
                    $ai_input: turn2Input,
                    $ai_output_choices: turn2Output,
                }),
            ])
            const turns = extractSessionTurns([t1, t2], { t1, t2 })
            expect(turns[1].isLoaded).toBe(true)
            // Pin the role sequence after dedup. The count alone wouldn't
            // catch silent content drift if `normalizeMessage` ever swapped
            // which parts merge or split.
            expect(turns[1].newInputs.map((m) => m.role)).toEqual(expectedNewInputRolesTurn2)
            // Output is always new content; never dedup'd.
            expect(turns[1].outputs.length).toBeGreaterThan(0)
        }
    )

    it.each(REAL_SHAPE_CASES)('signature is JSON-stringifiable for every turn 2 input ($name)', ({ turn2Input }) => {
        // Regression guard: if `normalizeMessage` ever returned a non-JSON-
        // stringifiable field (Date, function, undefined etc.) the signature
        // would silently throw at runtime. Walk every entry through the
        // signature path to ensure it stays stable for this shape.
        const t1 = makeTrace('t1', [
            makeGeneration('g1', '2026-05-11T00:00:00.000Z', {
                $ai_input: [],
                $ai_output_choices: [],
            }),
        ])
        const t2 = makeTrace('t2', [
            makeGeneration('g2', '2026-05-11T00:00:01.000Z', {
                $ai_input: turn2Input,
                $ai_output_choices: [],
            }),
        ])
        expect(() => extractSessionTurns([t1, t2], { t1, t2 })).not.toThrow()
    })
})
