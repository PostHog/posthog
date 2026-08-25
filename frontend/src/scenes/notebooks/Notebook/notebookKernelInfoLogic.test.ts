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
    ])('mode $mode polls kernel status: $shouldPoll', ({ mode, shortId, shouldPoll }) => {
        logic = notebookKernelInfoLogic({ shortId, mode })
        logic.mount()

        // A canvas has no server row, so a poll would 404 every 10 seconds until the page closes.
        jest.advanceTimersByTime(30_000)

        if (shouldPoll) {
            expect(kernelStatusSpy).toHaveBeenCalledWith(shortId)
        } else {
            expect(kernelStatusSpy).not.toHaveBeenCalled()
        }
    })
})
