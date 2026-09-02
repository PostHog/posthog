import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { notebookKernelInfoLogic } from './notebookKernelInfoLogic'
import type { NotebookLogicMode } from './notebookLogic'

const setHidden = (hidden: boolean): void => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden })
    document.dispatchEvent(new Event('visibilitychange'))
}

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
        setHidden(false)
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

    test('stops the refresh loop when the kea store is replaced under it', async () => {
        logic = notebookKernelInfoLogic({ shortId: 'store-reset-01890abc', mode: 'notebook' })
        logic.mount()
        await jest.advanceTimersByTimeAsync(30_000)

        const callsBeforeReset = kernelStatusSpy.mock.calls.length
        expect(callsBeforeReset).toBeGreaterThan(1)

        // Storybook resets the kea context on every story mount, which drops this logic's path
        // from the store without unmounting it. A tick that reads `values` after that throws
        // "[KEA] Can not find path", and in a story that surfaces as an unhandled error.
        initKeaTests()
        // The reset already dropped the logic, so the afterEach unmount has nothing to do.
        logic = undefined

        await jest.advanceTimersByTimeAsync(30_000)

        expect(kernelStatusSpy).toHaveBeenCalledTimes(callsBeforeReset)
    })

    test('a logic replaced at the same path keeps its own refresh loop', async () => {
        const shortId = 'remount-01890abc'
        logic = notebookKernelInfoLogic({ shortId, mode: 'notebook' })
        logic.mount()
        await jest.advanceTimersByTimeAsync(30_000)

        const callsPerMount = kernelStatusSpy.mock.calls.length
        expect(callsPerMount).toBeGreaterThan(1)

        // A storybook remount resets the context and then mounts the same notebook again, so the
        // replaced logic's loop finds a live logic sitting at its own path. Checking the path
        // alone lets it keep polling, which doubles the request rate for the new logic.
        initKeaTests()
        kernelStatusSpy.mockClear()
        logic = notebookKernelInfoLogic({ shortId, mode: 'notebook' })
        logic.mount()
        await jest.advanceTimersByTimeAsync(30_000)

        expect(kernelStatusSpy).toHaveBeenCalledTimes(callsPerMount)
    })

    test('re-arms the refresh loop when a remounted logic reuses its cache', async () => {
        logic = notebookKernelInfoLogic({ shortId: 'reused-cache-01890abc', mode: 'notebook' })
        logic.mount()
        await jest.advanceTimersByTimeAsync(30_000)

        const callsPerMount = kernelStatusSpy.mock.calls.length
        expect(callsPerMount).toBeGreaterThan(1)

        // Remounting a retained built logic keeps its cache and its kea context, the lifecycle
        // scratchpadLogic.test.ts exercises. The loop has to arm again instead of reading the
        // reused cache as a sign that the logic went away.
        logic.unmount()
        logic.mount()
        kernelStatusSpy.mockClear()
        await jest.advanceTimersByTimeAsync(30_000)

        // One fewer than a full window, because the mount request itself is already counted out.
        expect(kernelStatusSpy).toHaveBeenCalledTimes(callsPerMount - 1)
    })

    test('stays stopped when the tab returns after the kea store was replaced', async () => {
        logic = notebookKernelInfoLogic({ shortId: 'hidden-tab-01890abc', mode: 'notebook' })
        logic.mount()
        await jest.advanceTimersByTimeAsync(30_000)
        expect(kernelStatusSpy.mock.calls.length).toBeGreaterThan(1)

        initKeaTests()
        // The reset already dropped the logic, so the afterEach unmount has nothing to do.
        logic = undefined
        kernelStatusSpy.mockClear()

        // The plugin keeps every manager in a module-level set, so the reset leaves this one
        // registered. Going hidden and back reruns its setup, which has to stay inert instead of
        // reading `values` from a store without this logic's path. The plugin catches a throwing
        // setup and logs it, so the log is what separates an inert rerun from a reading one.
        const consoleErrorSpy = jest.spyOn(console, 'error')
        try {
            setHidden(true)
            setHidden(false)
            await jest.advanceTimersByTimeAsync(30_000)

            expect(kernelStatusSpy).not.toHaveBeenCalled()
            expect(consoleErrorSpy.mock.calls.flat().join(' ')).not.toContain('Disposable setup failed')
        } finally {
            consoleErrorSpy.mockRestore()
        }
    })
})
