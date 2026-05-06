import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
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
})
