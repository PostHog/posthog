import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import { notebooksKernelComputeOptionsRetrieve } from 'products/notebooks/frontend/generated/api'

import { notebookKernelInfoLogic } from './notebookKernelInfoLogic'
import type { NotebookLogicMode } from './notebookLogic'

jest.mock('products/notebooks/frontend/generated/api', () => ({
    notebooksKernelComputeOptionsRetrieve: jest.fn(),
}))

const COMPUTE_OPTIONS = {
    currency: 'USD',
    cpu_rate_per_core_hour: 0.2,
    memory_rate_per_gb_hour: 0.025,
    default_preset_key: 'small',
    presets: [
        { key: 'small', name: 'Small', description: '', cpu_cores: 1, memory_gb: 2, hourly_price: 0.25 },
        { key: 'balanced', name: 'Balanced', description: '', cpu_cores: 4, memory_gb: 8, hourly_price: 1 },
    ],
    allowed_cpu_cores: [1, 2, 4, 8],
    allowed_memory_gb: [2, 4, 8, 16],
    allowed_idle_timeout_seconds: [600, 1800],
}

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
        jest.mocked(notebooksKernelComputeOptionsRetrieve).mockResolvedValue(COMPUTE_OPTIONS)
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

    test('a failed options load blocks configuration instead of going quietly unpriced', async () => {
        // The loader's null is also its initial value, so a swallowed failure used to leave the
        // panel looking pre-pricing while Start stayed live.
        jest.mocked(notebooksKernelComputeOptionsRetrieve).mockRejectedValue(new Error('boom'))
        kernelStatusSpy.mockResolvedValue({ backend: 'modal', status: 'stopped', cpu_cores: 1, memory_gb: 2 })
        logic = notebookKernelInfoLogic({ shortId: 'options-fail-01890abc', mode: 'notebook' })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.computeOptionsFailed).toBe(true)
        expect(logic.values.computeBlockedReason).not.toBeNull()
    })

    test('Refresh retries the rates after they failed', async () => {
        jest.mocked(notebooksKernelComputeOptionsRetrieve).mockRejectedValueOnce(new Error('boom'))
        logic = notebookKernelInfoLogic({ shortId: 'options-retry-01890abc', mode: 'notebook' })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)
        expect(logic.values.computeOptions).toBeNull()

        // Refresh reloads both, which is the panel's retry affordance.
        jest.mocked(notebooksKernelComputeOptionsRetrieve).mockResolvedValue(COMPUTE_OPTIONS)
        logic.actions.loadKernelInfo()
        logic.actions.loadComputeOptions()
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.computeOptions).not.toBeNull()
        expect(logic.values.computeBlockedReason).toBeNull()
    })

    test('shows no price at all when the rates are unavailable', async () => {
        // The status endpoint's hourly_price describes the running sandbox, while the sliders
        // show the configured shape. Reusing it here would print a price for a shape that is not
        // on screen, so the panel shows none and blocks configuration instead.
        jest.mocked(notebooksKernelComputeOptionsRetrieve).mockRejectedValue(new Error('boom'))
        kernelStatusSpy.mockResolvedValue({
            backend: 'modal',
            status: 'running',
            cpu_cores: 4,
            memory_gb: 8,
            hourly_price: 1,
        })
        logic = notebookKernelInfoLogic({ shortId: 'no-price-01890abc', mode: 'notebook' })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)

        expect(logic.values.selectedHourlyPrice).toBeNull()
        expect(logic.values.computeBlockedReason).not.toBeNull()
    })

    test('does not restart again when the server already did', async () => {
        // A resize restarts the kernel server-side. Restarting again would tear down the sandbox
        // that was just built for the new shape.
        const configSpy = jest.spyOn(api.notebooks, 'kernelConfig').mockResolvedValue({ restarted: true })
        const restartSpy = jest.spyOn(api.notebooks, 'kernelRestart').mockResolvedValue({})
        logic = notebookKernelInfoLogic({ shortId: 'no-double-restart-01890abc', mode: 'notebook' })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)

        logic.actions.saveKernelConfig({ cpu_cores: 4, memory_gb: 8 }, 'restart')
        await jest.advanceTimersByTimeAsync(0)

        expect(configSpy).toHaveBeenCalled()
        expect(restartSpy).not.toHaveBeenCalled()
    })

    test('a shared notebook issues no team-scoped kernel requests', async () => {
        // A shared view renders from cachedNotebook so a logged-out viewer makes no team-scoped
        // call. Both kernel endpoints are team-scoped, so mounting here used to 401 twice.
        // The panel is not the only mount: notebookLogic connects this logic for every notebook,
        // and the exporter goes through that path, so isShared has to reach it from there.
        logic = notebookKernelInfoLogic({ shortId: 'shared-01890abc', mode: 'notebook', isShared: true })
        logic.mount()
        await jest.advanceTimersByTimeAsync(30_000)

        expect(kernelStatusSpy).not.toHaveBeenCalled()
        expect(jest.mocked(notebooksKernelComputeOptionsRetrieve)).not.toHaveBeenCalled()
    })

    test('quotes a hand-tuned shape at the rates the API returned', async () => {
        logic = notebookKernelInfoLogic({ shortId: 'pricing-01890abc', mode: 'notebook' })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)

        logic.actions.setCpuCores(8)
        logic.actions.setMemoryGb(16)

        // 8 x $0.20 + 16 x $0.025. A hardcoded rate anywhere in the widget fails here.
        expect(logic.values.selectedHourlyPrice).toBeCloseTo(2.0, 5)
        // No preset has this shape, so nothing should stay highlighted as selected.
        expect(logic.values.selectedPresetKey).toBeNull()
    })

    test('a preset sets both halves of the shape it is priced for', async () => {
        logic = notebookKernelInfoLogic({ shortId: 'preset-01890abc', mode: 'notebook' })
        logic.mount()
        await jest.advanceTimersByTimeAsync(0)

        const balanced = logic.values.computePresets.find((preset) => preset.key === 'balanced')!
        logic.actions.applyComputePreset(balanced)

        expect(logic.values.selectedCpu).toBe(balanced.cpu_cores)
        expect(logic.values.selectedMemory).toBe(balanced.memory_gb)
        // The preset's advertised price has to be what the user is then quoted.
        expect(logic.values.selectedHourlyPrice).toBeCloseTo(balanced.hourly_price, 5)
        expect(logic.values.selectedPresetKey).toBe('balanced')
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
