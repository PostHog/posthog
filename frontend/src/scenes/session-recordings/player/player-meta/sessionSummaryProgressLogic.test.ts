import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { sessionSummaryProgressLogic } from 'scenes/session-recordings/player/player-meta/sessionSummaryProgressLogic'

import { initKeaTests } from '~/test/init'

jest.mock('lib/api')
jest.mock('posthog-js')
jest.mock('lib/lemon-ui/LemonToast', () => ({
    lemonToast: {
        error: jest.fn(),
    },
}))

const SESSION_ID = 'test-session-1'

// Build a fake Response whose body reader closes immediately, so the listener's
// SSE while-loop terminates cleanly and we land in the `finally` block.
function makeNoopStreamResponse(): Response {
    return {
        body: {
            getReader: () => ({
                read: async () => ({ done: true, value: undefined }),
            }),
        },
    } as unknown as Response
}

// Build a fake Response that yields a single SSE chunk and then closes,
// enough to exercise the SSE parser's onEvent path inside the listener.
function makeStreamResponseWithChunks(chunks: string[]): Response {
    const encoder = new TextEncoder()
    const queue = chunks.map((c) => encoder.encode(c))
    return {
        body: {
            getReader: () => ({
                read: async () => {
                    const value = queue.shift()
                    if (!value) {
                        return { done: true, value: undefined }
                    }
                    return { done: false, value }
                },
            }),
        },
    } as unknown as Response
}

describe('sessionSummaryProgressLogic', () => {
    let logic: ReturnType<typeof sessionSummaryProgressLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = sessionSummaryProgressLogic()
        logic.mount()

        // Default API mocks; individual tests can override.
        ;(api as any).recordings = {
            summarizeStream: jest.fn().mockResolvedValue(makeNoopStreamResponse()),
            cancelSummarize: jest.fn().mockResolvedValue({ cancelled: true }),
        }
    })

    afterEach(() => {
        logic.unmount()
        jest.clearAllMocks()
    })

    describe('openBySessionId', () => {
        it('auto-opens on startSummarization', async () => {
            await expectLogic(logic, () => {
                logic.actions.startSummarization(SESSION_ID)
            }).toMatchValues({
                openBySessionId: expect.objectContaining({ [SESSION_ID]: true }),
            })
        })

        it('auto-opens on setSummary with content', async () => {
            await expectLogic(logic, () => {
                logic.actions.setSummary(SESSION_ID, { segments: [], key_actions: [] } as any)
            }).toMatchValues({
                openBySessionId: expect.objectContaining({ [SESSION_ID]: true }),
            })
        })

        it('persists user setSummaryOpen toggle (close stays closed)', async () => {
            logic.actions.startSummarization(SESSION_ID)
            await expectLogic(logic, () => {
                logic.actions.setSummaryOpen(SESSION_ID, false)
            }).toMatchValues({
                openBySessionId: expect.objectContaining({ [SESSION_ID]: false }),
            })
        })

        it('re-opens via setSummary after user closed, only if summary is non-null', async () => {
            logic.actions.startSummarization(SESSION_ID)
            logic.actions.setSummaryOpen(SESSION_ID, false)

            // Null summary should not reopen
            await expectLogic(logic, () => {
                logic.actions.setSummary(SESSION_ID, null)
            }).toMatchValues({
                openBySessionId: expect.objectContaining({ [SESSION_ID]: false }),
            })

            // Non-null summary should reopen
            await expectLogic(logic, () => {
                logic.actions.setSummary(SESSION_ID, { segments: [] } as any)
            }).toMatchValues({
                openBySessionId: expect.objectContaining({ [SESSION_ID]: true }),
            })
        })

        it('tracks open state independently per session', async () => {
            await expectLogic(logic, () => {
                logic.actions.startSummarization('session-a')
                logic.actions.setSummaryOpen('session-b', true)
            }).toMatchValues({
                openBySessionId: expect.objectContaining({
                    'session-a': true,
                    'session-b': true,
                }),
            })

            await expectLogic(logic, () => {
                logic.actions.setSummaryOpen('session-a', false)
            }).toMatchValues({
                openBySessionId: expect.objectContaining({
                    'session-a': false,
                    'session-b': true,
                }),
            })
        })
    })

    describe('cancelSummarization', () => {
        it('clears loading and progress state synchronously', async () => {
            await expectLogic(logic, () => {
                logic.actions.startSummarization(SESSION_ID)
            }).toMatchValues({
                loadingBySessionId: expect.objectContaining({ [SESSION_ID]: true }),
            })

            await expectLogic(logic, () => {
                logic.actions.cancelSummarization(SESSION_ID)
            }).toMatchValues({
                loadingBySessionId: expect.objectContaining({ [SESSION_ID]: false }),
                progressBySessionId: expect.objectContaining({ [SESSION_ID]: null }),
            })
        })

        it('fires backend cancel as fire-and-forget', async () => {
            await expectLogic(logic, () => {
                logic.actions.cancelSummarization(SESSION_ID)
            }).toFinishAllListeners()

            expect((api as any).recordings.cancelSummarize).toHaveBeenCalledWith(SESSION_ID)
        })
    })

    describe('error event parsing', () => {
        // Use fresh session ids — the module-level in-flight set shouldn't leak
        // between tests, but a unique id guarantees `startSummarization` actually
        // dispatches the listener body that opens the stream.
        let testCounter = 0
        const freshId = (label = 'err'): string => `${label}-${++testCounter}-${Date.now()}`

        it('parses JSON {message, retryable} and wires Try again button when retryable', async () => {
            const sessionId = freshId()
            const payload = JSON.stringify({
                message: 'PostHog is a little busy right now. Please try again in a few moments.',
                retryable: true,
                error_class: 'ClickHouseAtCapacity',
            })
            ;(api as any).recordings.summarizeStream = jest
                .fn()
                .mockResolvedValue(
                    makeStreamResponseWithChunks([`event: session-summary-error\ndata: ${payload}\n\n`])
                )

            await expectLogic(logic, () => {
                logic.actions.startSummarization(sessionId)
            }).toFinishAllListeners()

            expect((lemonToast.error as jest.Mock).mock.calls.length).toBeGreaterThan(0)
            const [message, options] = (lemonToast.error as jest.Mock).mock.calls[0]
            expect(message).toBe('PostHog is a little busy right now. Please try again in a few moments.')
            expect(options?.button?.label).toBe('Try again')

            expect(logic.values.errorBySessionId[sessionId]).toBe(
                'PostHog is a little busy right now. Please try again in a few moments.'
            )
        })

        it('hides retry button when retryable=false', async () => {
            const sessionId = freshId()
            const payload = JSON.stringify({
                message: "This recording can't be summarized. It may be too short or missing events.",
                retryable: false,
                error_class: 'ValidationError',
            })
            ;(api as any).recordings.summarizeStream = jest
                .fn()
                .mockResolvedValue(
                    makeStreamResponseWithChunks([`event: session-summary-error\ndata: ${payload}\n\n`])
                )

            await expectLogic(logic, () => {
                logic.actions.startSummarization(sessionId)
            }).toFinishAllListeners()

            const [, options] = (lemonToast.error as jest.Mock).mock.calls.at(-1) ?? []
            // Default lemonToast behavior (Get help button) — no custom Try again wired up
            expect(options?.button).toBeUndefined()
        })

        it('falls back to plain-string data when payload is not JSON', async () => {
            const sessionId = freshId()
            const legacy = 'Something went wrong while generating the summary. Please try again.'
            ;(api as any).recordings.summarizeStream = jest
                .fn()
                .mockResolvedValue(
                    makeStreamResponseWithChunks([`event: session-summary-error\ndata: ${legacy}\n\n`])
                )

            await expectLogic(logic, () => {
                logic.actions.startSummarization(sessionId)
            }).toFinishAllListeners()

            const [message, options] = (lemonToast.error as jest.Mock).mock.calls.at(-1) ?? []
            expect(message).toBe(legacy)
            // Legacy plain-string defaults to retryable, so a Try again button is wired up.
            expect(options?.button?.label).toBe('Try again')
            expect(logic.values.errorBySessionId[sessionId]).toBe(legacy)
        })
    })

    describe('forceRestart flag', () => {
        // The cancel-tracking + in-flight maps in the logic file are module
        // singletons, so each test uses a fresh session id to avoid leaking
        // state across tests.
        let testCounter = 0
        const freshId = (label = 's'): string => `${label}-${++testCounter}-${Date.now()}`

        it('first start sends forceRestart=false', async () => {
            const sessionId = freshId()
            await expectLogic(logic, () => {
                logic.actions.startSummarization(sessionId)
            }).toFinishAllListeners()

            expect((api as any).recordings.summarizeStream).toHaveBeenCalledWith(
                sessionId,
                expect.objectContaining({ forceRestart: false })
            )
        })

        it('start after a cancel sends forceRestart=true exactly once', async () => {
            const sessionId = freshId()
            await expectLogic(logic, () => {
                logic.actions.startSummarization(sessionId)
            }).toFinishAllListeners()
            await expectLogic(logic, () => {
                logic.actions.cancelSummarization(sessionId)
            }).toFinishAllListeners()

            // First start after cancel: forceRestart=true (TERMINATE_EXISTING)
            await expectLogic(logic, () => {
                logic.actions.startSummarization(sessionId)
            }).toFinishAllListeners()
            expect((api as any).recordings.summarizeStream).toHaveBeenLastCalledWith(
                sessionId,
                expect.objectContaining({ forceRestart: true })
            )

            // Second start without an intervening cancel: flag must reset to
            // false so an unrelated re-click doesn't kill an in-flight workflow.
            await expectLogic(logic, () => {
                logic.actions.startSummarization(sessionId)
            }).toFinishAllListeners()
            expect((api as any).recordings.summarizeStream).toHaveBeenLastCalledWith(
                sessionId,
                expect.objectContaining({ forceRestart: false })
            )
        })

        it('forceRestart is scoped per session id', async () => {
            const idA = freshId('a')
            const idB = freshId('b')
            await expectLogic(logic, () => {
                logic.actions.startSummarization(idA)
                logic.actions.startSummarization(idB)
            }).toFinishAllListeners()
            await expectLogic(logic, () => {
                logic.actions.cancelSummarization(idA)
            }).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.startSummarization(idA)
                logic.actions.startSummarization(idB)
            }).toFinishAllListeners()

            const calls = ((api as any).recordings.summarizeStream as jest.Mock).mock.calls
            const lastByA = [...calls].reverse().find((c) => c[0] === idA)
            const lastByB = [...calls].reverse().find((c) => c[0] === idB)
            expect(lastByA?.[1]).toEqual(expect.objectContaining({ forceRestart: true }))
            expect(lastByB?.[1]).toEqual(expect.objectContaining({ forceRestart: false }))
        })
    })
})
