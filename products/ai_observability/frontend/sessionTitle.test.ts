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

    it('collapses whitespace in the title', () => {
        const trace = makeTrace([], {
            inputState: {
                messages: [
                    {
                        role: 'user',
                        content: 'multi\nline\n\nmessage   with   spaces',
                    },
                ],
            },
        })
        expect(resolveSessionTitle(trace)).toBe('multi line message with spaces')
    })

    it('truncates long titles at a word boundary with an ellipsis', () => {
        const longMessage =
            "We've just released SpicyCam - I want to know what the initial user engagement and intent is like - are the users enjoying the new feature?"
        const trace = makeTrace([], {
            inputState: {
                messages: [{ role: 'user', content: longMessage }],
            },
        })
        const result = resolveSessionTitle(trace)
        expect(result).toBeTruthy()
        expect(result!.length).toBeLessThanOrEqual(121) // 120 + ellipsis
        expect(result!.endsWith('…')).toBe(true)
        // Word-boundary backoff: should not include the mid-word fragment "enjoyi".
        expect(result).not.toContain('enjoyi…')
    })

    it('does not truncate short titles', () => {
        const trace = makeTrace([], {
            inputState: {
                messages: [{ role: 'user', content: 'short message' }],
            },
        })
        expect(resolveSessionTitle(trace)).toBe('short message')
    })

    it('extracts text from array-shaped content (Anthropic typed parts)', () => {
        const trace = makeTrace([], {
            inputState: {
                messages: [
                    {
                        role: 'user',
                        content: [
                            { type: 'text', text: 'Look at this image' },
                            { type: 'image', url: 'https://example.com/a.png' },
                        ],
                    },
                ],
            },
        })
        expect(resolveSessionTitle(trace)).toBe('Look at this image')
    })

    it('skips messages with empty content and uses the next user message', () => {
        const trace = makeTrace([], {
            inputState: {
                messages: [
                    { role: 'user', content: '' },
                    { role: 'user', content: 'actual question' },
                ],
            },
        })
        expect(resolveSessionTitle(trace)).toBe('actual question')
    })

    it('accepts a custom maxLength', () => {
        const trace = makeTrace([], {
            inputState: {
                messages: [{ role: 'user', content: 'this is a moderately long sentence that should be cut' }],
            },
        })
        const result = resolveSessionTitle(trace, 20)
        expect(result).toBeTruthy()
        expect(result!.length).toBeLessThanOrEqual(21)
    })
})
