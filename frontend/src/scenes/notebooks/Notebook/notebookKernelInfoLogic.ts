import { actions, afterMount, beforeUnmount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { PythonKernelExecuteResponse } from '../Nodes/pythonExecution'
import type { notebookKernelInfoLogicType } from './notebookKernelInfoLogicType'

export type NotebookKernelInfo = {
    backend: 'docker' | 'modal' | null
    status: string
    last_used_at?: string | null
    last_error?: string | null
    runtime_id?: string | null
    kernel_id?: string | null
    kernel_pid?: number | null
    sandbox_id?: string | null
    cpu_cores?: number | null
    memory_gb?: number | null
    disk_size_gb?: number | null
    idle_timeout_seconds?: number | null
}

export type NotebookKernelInfoLogicProps = {
    shortId: string
}

export const cpuCoreOptions = [0.125, 0.25, 0.5, 1, 2, 4, 6, 8, 16, 32, 64]
export const memoryGbOptions = [0.25, 0.5, 1, 2, 4, 8, 16, 32, 64, 128, 256]
export const idleTimeoutOptions = [
    { label: '10 minutes', value: 600 },
    { label: '30 minutes', value: 1800 },
    { label: '1 hour', value: 3600 },
    { label: '3 hours', value: 10800 },
    { label: '6 hours', value: 21600 },
    { label: '12 hours', value: 43200 },
]

export type KernelActionInFlight = {
    start: boolean
    stop: boolean
    restart: boolean
    execute: boolean
    save: boolean
    refresh: boolean
}

const findClosestOptionIndex = (options: number[], value?: number | null): number => {
    if (value == null || Number.isNaN(value)) {
        return 0
    }
    const matchIndex = options.findIndex((option) => Math.abs(option - value) < 1e-6)
    if (matchIndex !== -1) {
        return matchIndex
    }
    return options.reduce((closestIndex, option, index) => {
        const closestValue = options[closestIndex]
        return Math.abs(option - value) < Math.abs(closestValue - value) ? index : closestIndex
    }, 0)
}

export const notebookKernelInfoLogic = kea<notebookKernelInfoLogicType>([
    props({} as NotebookKernelInfoLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'notebookKernelInfoLogic', key]),
    key(({ shortId }) => shortId),
    actions({
        executeKernel: (code) => ({ code }),
        setCode: (code: string) => ({ code }),
        setCpuIndex: (cpuIndex: number) => ({ cpuIndex }),
        setMemoryIndex: (memoryIndex: number) => ({ memoryIndex }),
        setIdleTimeoutSeconds: (idleTimeoutSeconds: number) => ({ idleTimeoutSeconds }),
        resetConfigToKernel: true,
        setConfigFromKernelInfo: (config: { cpuIndex: number; memoryIndex: number; idleTimeoutSeconds: number }) => ({
            config,
        }),
        startKernel: true,
        stopKernel: true,
        restartKernel: true,
        saveKernelConfig: (
            config: { cpu_cores?: number; memory_gb?: number; idle_timeout_seconds?: number },
            nextAction: 'start' | 'restart'
        ) => ({
            config,
            nextAction,
        }),
        saveKernelConfigFailure: true,
        clearExecution: true,
    }),
    reducers({
        code: [
            'print("Kernel ready")',
            {
                setCode: (_, { code }) => code,
            },
        ],
        cpuIndex: [
            0,
            {
                setCpuIndex: (_, { cpuIndex }) => cpuIndex,
                setConfigFromKernelInfo: (_, { config }) => config.cpuIndex,
            },
        ],
        memoryIndex: [
            0,
            {
                setMemoryIndex: (_, { memoryIndex }) => memoryIndex,
                setConfigFromKernelInfo: (_, { config }) => config.memoryIndex,
            },
        ],
        idleTimeoutSeconds: [
            idleTimeoutOptions[1].value,
            {
                setIdleTimeoutSeconds: (_, { idleTimeoutSeconds }) => idleTimeoutSeconds,
                setConfigFromKernelInfo: (_, { config }) => config.idleTimeoutSeconds,
            },
        ],
        isEditingConfig: [
            false,
            {
                setCpuIndex: () => true,
                setMemoryIndex: () => true,
                setIdleTimeoutSeconds: () => true,
                setConfigFromKernelInfo: () => false,
                resetConfigToKernel: () => false,
                saveKernelConfig: () => false,
                saveKernelConfigFailure: () => true,
            },
        ],
        actionInFlight: [
            {
                start: false,
                stop: false,
                restart: false,
                execute: false,
                save: false,
                refresh: false,
            } as KernelActionInFlight,
            {
                startKernel: (state) => ({ ...state, start: true }),
                stopKernel: (state) => ({ ...state, stop: true }),
                restartKernel: (state) => ({ ...state, restart: true }),
                executeKernel: (state) => ({ ...state, execute: true }),
                saveKernelConfig: (state) => ({ ...state, save: true }),
                loadKernelInfo: (state) => ({ ...state, refresh: true }),
                loadKernelInfoSuccess: (state, { kernelInfo }) => ({
                    ...state,
                    start: false,
                    stop: state.stop && kernelInfo?.status === 'running',
                    restart: false,
                    save: false,
                    refresh: false,
                }),
                loadKernelInfoFailure: (state) => ({
                    ...state,
                    start: false,
                    stop: false,
                    restart: false,
                    save: false,
                    refresh: false,
                }),
                executeKernelSuccess: (state) => ({ ...state, execute: false }),
                executeKernelFailure: (state) => ({ ...state, execute: false }),
                saveKernelConfigFailure: (state) => ({ ...state, save: false }),
            },
        ],
    }),
    loaders(({ props }) => ({
        kernelInfo: [
            null as NotebookKernelInfo | null,
            {
                loadKernelInfo: async () => {
                    try {
                        const response = (await api.notebooks.kernelStatus(props.shortId)) as NotebookKernelInfo
                        return response.backend ? response : null
                    } catch {
                        return null
                    }
                },
            },
        ],
        executionResult: [
            null as PythonKernelExecuteResponse | null,
            {
                executeKernel: async ({ code }): Promise<PythonKernelExecuteResponse | null> => {
                    return (await api.notebooks.kernelExecute(props.shortId, {
                        code,
                        return_variables: false,
                    })) as PythonKernelExecuteResponse
                },
            },
        ],
    })),
    selectors({
        isRunning: [
            (s) => [s.kernelInfo],
            (kernelInfo) =>
                kernelInfo?.status === 'running' ||
                (kernelInfo?.status === 'starting' && kernelInfo?.last_error == null),
        ],
        statusInfo: [
            (s) => [s.kernelInfo, s.actionInFlight],
            (kernelInfo, actionInFlight) => {
                if (!kernelInfo) {
                    return null
                }
                if (actionInFlight.stop) {
                    return { label: 'Stopping', tone: 'warning' as const }
                }
                if (actionInFlight.restart) {
                    return { label: 'Restarting', tone: 'warning' as const }
                }
                if (actionInFlight.start && kernelInfo.status !== 'starting') {
                    return { label: 'Starting', tone: 'warning' as const }
                }
                if (kernelInfo.last_error) {
                    return { label: 'Error', tone: 'danger' as const }
                }
                const statusTone: Record<
                    string,
                    { label: string; tone: 'success' | 'warning' | 'danger' | 'default' }
                > = {
                    running: { label: 'Running', tone: 'success' },
                    starting: { label: 'Starting', tone: 'warning' },
                    stopped: { label: 'Stopped', tone: 'default' },
                    timed_out: { label: 'Timed out', tone: 'warning' },
                    discarded: { label: 'Discarded', tone: 'default' },
                    error: { label: 'Error', tone: 'danger' },
                }
                return statusTone[kernelInfo.status] ?? { label: kernelInfo.status, tone: 'default' }
            },
        ],
        isStarting: [
            (s) => [s.kernelInfo, s.actionInFlight],
            (kernelInfo, actionInFlight) =>
                (kernelInfo?.status === 'starting' && kernelInfo?.last_error == null) || actionInFlight.start,
        ],
        isBusyStatus: [
            (s) => [s.isStarting, s.actionInFlight],
            (isStarting, actionInFlight) => isStarting || actionInFlight.stop || actionInFlight.restart,
        ],
        hasActionInFlight: [(s) => [s.actionInFlight], (actionInFlight) => Object.values(actionInFlight).some(Boolean)],
        isModalKernel: [(s) => [s.kernelInfo], (kernelInfo) => kernelInfo?.backend === 'modal'],
        selectedCpu: [(s) => [s.cpuIndex], (cpuIndex) => cpuCoreOptions[cpuIndex]],
        selectedMemory: [(s) => [s.memoryIndex], (memoryIndex) => memoryGbOptions[memoryIndex]],
        currentCpu: [
            (s) => [s.kernelInfo, s.selectedCpu],
            (kernelInfo, selectedCpu) => kernelInfo?.cpu_cores ?? selectedCpu,
        ],
        currentMemory: [
            (s) => [s.kernelInfo, s.selectedMemory],
            (kernelInfo, selectedMemory) => kernelInfo?.memory_gb ?? selectedMemory,
        ],
        currentIdleTimeout: [
            (s) => [s.kernelInfo],
            (kernelInfo) => kernelInfo?.idle_timeout_seconds ?? idleTimeoutOptions[1].value,
        ],
        hasConfigChanges: [
            (s) => [
                s.kernelInfo,
                s.selectedCpu,
                s.selectedMemory,
                s.idleTimeoutSeconds,
                s.currentCpu,
                s.currentMemory,
                s.currentIdleTimeout,
            ],
            (
                kernelInfo,
                selectedCpu,
                selectedMemory,
                idleTimeoutSeconds,
                currentCpu,
                currentMemory,
                currentIdleTimeout
            ) =>
                Boolean(
                    kernelInfo &&
                        (Math.abs(selectedCpu - currentCpu) > 1e-6 ||
                            Math.abs(selectedMemory - currentMemory) > 1e-6 ||
                            idleTimeoutSeconds !== currentIdleTimeout)
                ),
        ],
    }),
    listeners(({ actions, props, values }) => ({
        startKernel: async () => {
            try {
                await api.notebooks.kernelStart(props.shortId)
            } finally {
                actions.loadKernelInfo()
            }
        },
        stopKernel: async () => {
            try {
                await api.notebooks.kernelStop(props.shortId)
            } finally {
                actions.loadKernelInfo()
            }
        },
        restartKernel: async () => {
            try {
                await api.notebooks.kernelRestart(props.shortId)
            } finally {
                actions.loadKernelInfo()
            }
        },
        saveKernelConfig: async ({ config, nextAction }) => {
            try {
                await api.notebooks.kernelConfig(props.shortId, config)
            } catch {
                actions.saveKernelConfigFailure()
                return
            }
            if (nextAction === 'start') {
                actions.startKernel()
                return
            }
            actions.restartKernel()
        },
        loadKernelInfoSuccess: ({ kernelInfo }) => {
            if (!kernelInfo) {
                return
            }
            if (values.isEditingConfig && values.hasConfigChanges) {
                return
            }
            actions.setConfigFromKernelInfo({
                cpuIndex: findClosestOptionIndex(cpuCoreOptions, kernelInfo.cpu_cores),
                memoryIndex: findClosestOptionIndex(memoryGbOptions, kernelInfo.memory_gb),
                idleTimeoutSeconds: kernelInfo.idle_timeout_seconds ?? idleTimeoutOptions[1].value,
            })
        },
        resetConfigToKernel: () => {
            if (!values.kernelInfo) {
                return
            }
            actions.setConfigFromKernelInfo({
                cpuIndex: findClosestOptionIndex(cpuCoreOptions, values.kernelInfo.cpu_cores),
                memoryIndex: findClosestOptionIndex(memoryGbOptions, values.kernelInfo.memory_gb),
                idleTimeoutSeconds: values.kernelInfo.idle_timeout_seconds ?? idleTimeoutOptions[1].value,
            })
        },
        executeKernelSuccess: () => {
            actions.loadKernelInfo()
        },
        executeKernelFailure: () => {
            actions.loadKernelInfo()
        },
        clearExecution: () => {
            actions.executeKernelSuccess(null)
        },
    })),
    afterMount(({ actions, cache, values }) => {
        const scheduleRefresh = (): void => {
            const delayMs = values.isStarting ? 2000 : 10000
            cache.kernelInfoRefresh = window.setTimeout(() => {
                if (!values.actionInFlight.refresh) {
                    actions.loadKernelInfo()
                }
                scheduleRefresh()
            }, delayMs)
        }
        actions.loadKernelInfo()
        scheduleRefresh()
    }),
    beforeUnmount(({ cache }) => {
        if (cache.kernelInfoRefresh) {
            clearTimeout(cache.kernelInfoRefresh)
        }
    }),
])
