import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { notebookKernelInfoLogic } from './notebookKernelInfoLogic'
import type { NotebookLogicMode } from './notebookLogic'

describe('notebookKernelInfoLogic', () => {
    let kernelStatusSpy: jest.SpyInstance
    let logic: ReturnType<typeof notebookKernelInfoLogic.build> | undefined

    beforeEach(() => {
        initKeaTests()
        kernelStatusSpy = jest
            .spyOn(api.notebooks, 'kernelStatus')
            .mockResolvedValue({ backend: null, status: 'stopped' })
        jest.useFakeTimers()
    })

    afterEach(() => {
        logic?.unmount()
        logic = undefined
        jest.useRealTimers()
        kernelStatusSpy.mockRestore()
    })

    test.each([
        { mode: 'notebook' as NotebookLogicMode, shortId: 'abc123', shouldPoll: true },
        { mode: undefined, shortId: 'def456', shouldPoll: true },
        { mode: 'canvas' as NotebookLogicMode, shortId: 'canvas-01890abc', shouldPoll: false },
    ])('mode $mode polls kernel status: $shouldPoll', async ({ mode, shortId, shouldPoll }) => {
        logic = notebookKernelInfoLogic({ shortId, mode })
        logic.mount()

        // afterMount fetches once on its own, so pin that count before any timer runs. Asserting
        // only that the spy was called would pass just as well with the refresh loop deleted.
        expect(kernelStatusSpy).toHaveBeenCalledTimes(shouldPoll ? 1 : 0)

        // A canvas has no server row, so a poll would 404 every 10 seconds until the page closes.
        // Advance asynchronously: each tick skips its fetch while the previous one is still in
        // flight, so the loop only advances if the mocked request settles between ticks.
        await jest.advanceTimersByTimeAsync(30_000)

        if (shouldPoll) {
            // Strictly more than the mount fetch, which is what shows the loop re-arms.
            expect(kernelStatusSpy.mock.calls.length).toBeGreaterThan(1)
            expect(kernelStatusSpy).toHaveBeenCalledWith(shortId)
        } else {
            expect(kernelStatusSpy).not.toHaveBeenCalled()
        }
    })
})
