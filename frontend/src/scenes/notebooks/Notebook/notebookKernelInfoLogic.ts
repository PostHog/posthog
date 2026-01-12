import { actions, afterMount, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { PythonKernelExecuteResponse } from '../Nodes/pythonExecution'
import type { notebookKernelInfoLogicType } from './notebookKernelInfoLogicType'

export type NotebookKernelInfo = {
    backend: 'local' | 'modal'
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
}

export type NotebookKernelInfoLogicProps = {
    shortId: string
}

export const notebookKernelInfoLogic = kea<notebookKernelInfoLogicType>([
    props({} as NotebookKernelInfoLogicProps),
    path((key) => ['scenes', 'notebooks', 'Notebook', 'notebookKernelInfoLogic', key]),
    actions({
        executeKernel: (code) => ({ code }),
        startKernel: true,
        stopKernel: true,
        restartKernel: true,
        clearExecution: true,
    }),
    reducers({
        actionInFlight: [
            false,
            {
                startKernel: () => true,
                stopKernel: () => true,
                restartKernel: () => true,
                executeKernel: () => true,
                loadKernelInfoSuccess: () => false,
                loadKernelInfoFailure: () => false,
                executeKernelSuccess: () => false,
                executeKernelFailure: () => false,
            },
        ],
    }),
    loaders(({ props }) => ({
        kernelInfo: [
            null as NotebookKernelInfo | null,
            {
                loadKernelInfo: async () => {
                    return await api.notebooks.kernelStatus(props.shortId)
                },
            },
        ],
        executionResult: [
            null as PythonKernelExecuteResponse | null,
            {
                executeKernel: async ({ code }) => {
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
            (kernelInfo) => kernelInfo?.status === 'running' || kernelInfo?.status === 'starting',
        ],
    }),
    listeners(({ actions, props }) => ({
        startKernel: async () => {
            await api.notebooks.kernelStart(props.shortId)
            actions.loadKernelInfo()
        },
        stopKernel: async () => {
            await api.notebooks.kernelStop(props.shortId)
            actions.loadKernelInfo()
        },
        restartKernel: async () => {
            await api.notebooks.kernelRestart(props.shortId)
            actions.loadKernelInfo()
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
    afterMount(({ actions }) => {
        actions.loadKernelInfo()
    }),
])
