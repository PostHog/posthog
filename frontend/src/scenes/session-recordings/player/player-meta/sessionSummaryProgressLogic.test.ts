import { expectLogic } from 'kea-test-utils'

import api, { ApiError } from 'lib/api'
import { sessionSummaryProgressLogic } from 'scenes/session-recordings/player/player-meta/sessionSummaryProgressLogic'

import { initKeaTests } from '~/test/init'

jest.mock('lib/api')
jest.mock('posthog-js')

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

    describe('error surfacing on failure', () => {
        // Before this fix the catch/timeout paths only flipped loading off without setting an error,
        // so PlayerSummaryDock silently collapsed back to the entry-point button. The dock decides
        // what to render via `hasSummary || sessionSummaryLoading || !!sessionSummaryError` — without
        // any of these flags set, users had no idea their summarization attempt had failed.
        let testCounter = 0
        const freshId = (label = 's'): string => `${label}-err-${++testCounter}-${Date.now()}`

        it('sets an error when the stream fails with an ApiError', async () => {
            const sessionId = freshId()
            // `jest.mock('lib/api')` auto-mocks `ApiError` — `new ApiError(...)` returns an instance
            // whose prototype chain still satisfies `instanceof ApiError`, but the original
            // constructor (which calls `super(message)`) is replaced with a no-op. Assign `message`
            // manually so the logic's `err.message` read sees the value under test.
            const apiError = new ApiError()
            ;(apiError as any).message = 'Bad gateway'
            ;((api as any).recordings.summarizeStream as jest.Mock).mockRejectedValueOnce(apiError)

            await expectLogic(logic, () => {
                logic.actions.startSummarization(sessionId)
            }).toFinishAllListeners()

            expect(logic.values.errorBySessionId[sessionId]).toBe('Bad gateway')
            expect(logic.values.loadingBySessionId[sessionId]).toBe(false)
        })

        it('sets a generic error when the stream fails with an unexpected exception', async () => {
            const sessionId = freshId()
            ;((api as any).recordings.summarizeStream as jest.Mock).mockRejectedValueOnce(new Error('connection reset'))

            await expectLogic(logic, () => {
                logic.actions.startSummarization(sessionId)
            }).toFinishAllListeners()

            expect(logic.values.errorBySessionId[sessionId]).toEqual(expect.stringContaining('Something went wrong'))
            expect(logic.values.loadingBySessionId[sessionId]).toBe(false)
        })

        it('sets an error when the 10-minute summarization timeout fires', async () => {
            jest.useFakeTimers()
            const sessionId = freshId()
            // Block the stream so the timeout wins the race.
            ;((api as any).recordings.summarizeStream as jest.Mock).mockImplementationOnce(() => new Promise(() => {}))

            logic.actions.startSummarization(sessionId)

            // SUMMARIZATION_TIMEOUT_MS is 10 minutes — advance past it.
            jest.advanceTimersByTime(10 * 60 * 1000 + 1)

            expect(logic.values.errorBySessionId[sessionId]).toEqual(
                expect.stringContaining('taking longer than expected')
            )
            expect(logic.values.loadingBySessionId[sessionId]).toBe(false)
            jest.useRealTimers()
        })

        it('does not set an error on user-initiated cancellation', async () => {
            const sessionId = freshId()
            // Hold the stream open so we can cancel before it finishes.
            ;((api as any).recordings.summarizeStream as jest.Mock).mockImplementationOnce(
                async ({ signal }: { signal: AbortSignal }) =>
                    new Promise((_, reject) => {
                        signal.addEventListener('abort', () => {
                            const abortErr = new DOMException('aborted', 'AbortError')
                            reject(abortErr)
                        })
                    })
            )

            logic.actions.startSummarization(sessionId)
            await expectLogic(logic, () => {
                logic.actions.cancelSummarization(sessionId)
            }).toFinishAllListeners()

            expect(logic.values.errorBySessionId[sessionId] ?? null).toBeNull()
            expect(logic.values.loadingBySessionId[sessionId]).toBe(false)
        })
    })
})
