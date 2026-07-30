import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { notebookKernelInfoLogic } from './notebookKernelInfoLogic'

const POLL_INTERVAL_MS = 10000

describe('notebookKernelInfoLogic', () => {
    let kernelStatusSpy: jest.SpyInstance
    let logic: ReturnType<typeof notebookKernelInfoLogic.build>

    // Fake timers stall kea-test-utils' own waits, so flush the microtask queue by hand
    const flush = async (): Promise<void> => {
        for (let i = 0; i < 10; i++) {
            await Promise.resolve()
        }
    }

    const tick = async (): Promise<void> => {
        jest.advanceTimersByTime(POLL_INTERVAL_MS)
        await flush()
    }

    beforeEach(() => {
        jest.useFakeTimers()
        initKeaTests()
        kernelStatusSpy = jest.spyOn(api.notebooks, 'kernelStatus').mockResolvedValue({ backend: 'docker' })
    })

    afterEach(() => {
        logic?.unmount()
        kernelStatusSpy.mockRestore()
        jest.useRealTimers()
    })

    it('keeps polling kernel status for a persisted notebook', async () => {
        logic = notebookKernelInfoLogic({ shortId: 'abc123' })
        logic.mount()
        await flush()

        await tick()

        expect(kernelStatusSpy).toHaveBeenCalledWith('abc123')
        expect(kernelStatusSpy).toHaveBeenCalledTimes(2)
    })

    // Templates and canvases have no notebook row, so any kernel request 404s. The poll used to fire
    // anyway, once on mount and then every 10s for as long as the notebook stayed open.
    it.each([
        ['template', 'template-introduction'],
        ['canvas', 'canvas-abc123'],
    ])('does not request kernel status for a %s', async (_, shortId) => {
        logic = notebookKernelInfoLogic({ shortId })
        logic.mount()
        await flush()

        await tick()

        expect(kernelStatusSpy).not.toHaveBeenCalled()
        expect(logic.values.kernelInfo).toBeNull()
    })

    it('stops polling once the notebook itself is gone', async () => {
        kernelStatusSpy.mockRejectedValue({ status: 404 })
        logic = notebookKernelInfoLogic({ shortId: 'abc123' })
        logic.mount()
        await flush()

        await tick()
        await tick()

        expect(kernelStatusSpy).toHaveBeenCalledTimes(1)
    })
})
