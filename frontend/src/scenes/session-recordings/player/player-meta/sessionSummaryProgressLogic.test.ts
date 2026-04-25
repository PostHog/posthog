import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { sessionSummaryProgressLogic } from 'scenes/session-recordings/player/player-meta/sessionSummaryProgressLogic'

import { initKeaTests } from '~/test/init'

const SESSION_ID = 'test-session-1'

// jsdom does not expose ReadableStream, so build a minimal stub that satisfies
// the shape that sessionSummaryProgressLogic reads from `response.body.getReader()`.
const buildSseResponse = (chunks: string[]): Response => {
    const encoder = new TextEncoder()
    const queue: Uint8Array[] = chunks.map((chunk) => encoder.encode(chunk))
    const reader = {
        read: async (): Promise<{ done: boolean; value?: Uint8Array }> => {
            const next = queue.shift()
            if (next === undefined) {
                return { done: true, value: undefined }
            }
            return { done: false, value: next }
        },
    }
    return {
        body: {
            getReader: () => reader,
        },
    } as unknown as Response
}

describe('sessionSummaryProgressLogic', () => {
    let logic: ReturnType<typeof sessionSummaryProgressLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = sessionSummaryProgressLogic()
        logic.mount()
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

    describe('stream lifecycle', () => {
        afterEach(() => {
            jest.restoreAllMocks()
        })

        it('clears loading and surfaces an error when the SSE stream ends without a terminal event', async () => {
            // Use a fresh session id so the module-scoped inFlightSessionIds Set
            // from previous tests in this file does not short-circuit the listener.
            const sessionId = 'stream-no-terminal-event'
            // Stream emits only a progress event then closes — no summary, no error.
            // Without the fix, loadingBySessionId stays true until the 10-minute timeout.
            const progressChunk = 'event: session-summary-progress\ndata: {"step":1,"phase":"rasterizing"}\n\n'
            jest.spyOn(api.recordings, 'summarizeStream').mockResolvedValue(buildSseResponse([progressChunk]))

            await expectLogic(logic, () => {
                logic.actions.startSummarization(sessionId)
            })
                .toDispatchActions(['startSummarization', 'setProgress', 'setError'])
                .toMatchValues({
                    loadingBySessionId: expect.objectContaining({ [sessionId]: false }),
                    errorBySessionId: expect.objectContaining({
                        [sessionId]: 'Summary stream ended unexpectedly. Please try again.',
                    }),
                })
        })

        it('keeps loading off after a successful summary stream', async () => {
            const sessionId = 'stream-with-summary'
            const summaryChunk = 'data: {"segments":[],"key_actions":[]}\n\n'
            jest.spyOn(api.recordings, 'summarizeStream').mockResolvedValue(buildSseResponse([summaryChunk]))

            await expectLogic(logic, () => {
                logic.actions.startSummarization(sessionId)
            })
                .toDispatchActions(['startSummarization', 'setSummary'])
                .toMatchValues({
                    loadingBySessionId: expect.objectContaining({ [sessionId]: false }),
                    errorBySessionId: expect.objectContaining({ [sessionId]: null }),
                })
        })
    })
})
