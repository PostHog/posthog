import {
    LogicWrapper,
    MakeLogicType,
    actions,
    afterMount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
} from 'kea'
import posthog from 'posthog-js'
import { v4 as uuidv4 } from 'uuid'

import { ApiError } from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import {
    notebooksGenuiCancel,
    notebooksGenuiFrame,
    notebooksGenuiGenerate,
    notebooksGenuiStatus,
} from 'products/notebooks/frontend/generated/api'
import type { GenUIFrameApi, GenUIStatusApi } from 'products/notebooks/frontend/generated/api.schemas'

import type { GenUIModel } from './genUIModels'

const STATUS_POLL_INTERVAL_MS = 1_000
const STATUS_POLL_MAX_ATTEMPTS = 120

export type NotebookNodeGenUILogicProps = {
    notebookShortId: string
    nodeId: string
    prompt: string
    model: GenUIModel
    isEditable: boolean
}

export interface notebookNodeGenUILogicValues {
    currentTeamId: number | null
    cancellationInFlight: boolean
    error: string | null
    frameRevision: number
    generationInFlight: boolean
    pollAttempts: number
    runtimeError: string | null
    status: GenUIStatusApi | null
    statusLoading: boolean
}

export interface notebookNodeGenUILogicActions {
    cancelGeneration: () => { value: true }
    cancellationFailed: (error: string) => { error: string }
    cancellationStarted: () => { value: true }
    generateVisualization: () => { value: true }
    generationCanceled: () => { value: true }
    generationFailed: (error: string) => { error: string }
    generationStarted: () => { value: true }
    loadStatus: () => { value: true }
    refreshData: () => { value: true }
    setRuntimeError: (error: string | null) => { error: string | null }
    statusFailed: (error: string) => { error: string }
    statusReceived: (status: GenUIStatusApi) => { status: GenUIStatusApi }
}

export interface notebookNodeGenUILogicMeta {
    key: string
}

export type notebookNodeGenUILogicType = MakeLogicType<
    notebookNodeGenUILogicValues,
    notebookNodeGenUILogicActions,
    NotebookNodeGenUILogicProps,
    notebookNodeGenUILogicMeta
>

function errorMessage(error: unknown): string {
    if (error instanceof ApiError) {
        const response = error.data as { detail?: unknown } | undefined
        if (typeof response?.detail === 'string') {
            return response.detail
        }
    }
    return error instanceof Error ? error.message : 'The visualization request failed.'
}

function isCancellationError(error: unknown): boolean {
    if (error instanceof ApiError) {
        const response = error.data as { code?: unknown } | undefined
        return response?.code === 'generation_canceled'
    }
    return error instanceof Error && error.name === 'AbortError'
}

function shouldPoll(status: GenUIStatusApi | null): boolean {
    return status?.lifecycle_status === 'building'
}

export async function loadGenUIFrame(
    projectId: string,
    notebookShortId: string,
    nodeId: string,
    frameName: string
): Promise<GenUIFrameApi> {
    return await notebooksGenuiFrame(projectId, notebookShortId, nodeId, frameName)
}

export const notebookNodeGenUILogic: LogicWrapper<notebookNodeGenUILogicType> = kea<notebookNodeGenUILogicType>([
    props({} as NotebookNodeGenUILogicProps),
    key((props) => `${props.notebookShortId}-${props.nodeId}`),
    path((key) => ['scenes', 'notebooks', 'Nodes', 'notebookNodeGenUILogic', key]),
    connect({ values: [teamLogic, ['currentTeamId']] }),
    actions({
        cancelGeneration: true,
        cancellationFailed: (error: string) => ({ error }),
        cancellationStarted: true,
        generateVisualization: true,
        generationCanceled: true,
        generationFailed: (error: string) => ({ error }),
        generationStarted: true,
        loadStatus: true,
        refreshData: true,
        setRuntimeError: (error: string | null) => ({ error }),
        statusFailed: (error: string) => ({ error }),
        statusReceived: (status: GenUIStatusApi) => ({ status }),
    }),
    reducers({
        cancellationInFlight: [
            false,
            {
                cancellationStarted: () => true,
                cancellationFailed: () => false,
                generationCanceled: () => false,
            },
        ],
        status: [
            null as GenUIStatusApi | null,
            {
                statusReceived: (_, { status }) => status,
            },
        ],
        statusLoading: [
            false,
            {
                loadStatus: () => true,
                statusFailed: () => false,
                statusReceived: () => false,
            },
        ],
        generationInFlight: [
            false,
            {
                generationStarted: () => true,
                generationCanceled: () => false,
                generationFailed: () => false,
                statusReceived: () => false,
            },
        ],
        error: [
            null as string | null,
            {
                generationStarted: () => null,
                cancellationFailed: (_, { error }) => error,
                generationCanceled: () => null,
                generationFailed: (_, { error }) => error,
                statusFailed: (_, { error }) => error,
                statusReceived: () => null,
            },
        ],
        runtimeError: [
            null as string | null,
            {
                setRuntimeError: (_, { error }) => error,
                refreshData: () => null,
            },
        ],
        frameRevision: [
            0,
            {
                refreshData: (revision) => revision + 1,
            },
        ],
        pollAttempts: [
            0,
            {
                generationStarted: () => 0,
                statusFailed: (attempts) => attempts + 1,
                statusReceived: (attempts, { status }) => (shouldPoll(status) ? attempts + 1 : 0),
            },
        ],
    }),
    listeners(({ actions, values, props, cache }) => {
        const scheduleStatusPoll = (): void => {
            cache.disposables.dispose('statusPoll')
            if (values.pollAttempts >= STATUS_POLL_MAX_ATTEMPTS) {
                actions.statusFailed('Building is taking longer than expected. Reload the notebook to check again.')
                return
            }
            cache.disposables.add(() => {
                const timeoutId = window.setTimeout(() => actions.loadStatus(), STATUS_POLL_INTERVAL_MS)
                return () => window.clearTimeout(timeoutId)
            }, 'statusPoll')
        }

        return {
            cancelGeneration: async () => {
                const generationId = cache.activeGenerationId
                if (!generationId || !values.currentTeamId || cache.cancellationInFlight) {
                    return
                }
                cache.cancellationInFlight = true
                actions.cancellationStarted()
                try {
                    await notebooksGenuiCancel(String(values.currentTeamId), props.notebookShortId, props.nodeId, {
                        generation_id: generationId,
                    })
                    cache.generationAbortController?.abort()
                    actions.generationCanceled()
                } catch (error) {
                    const message = errorMessage(error)
                    posthog.captureException(error instanceof Error ? error : new Error(message), {
                        action: 'cancel notebook visualization generation',
                    })
                    actions.cancellationFailed(message)
                } finally {
                    cache.cancellationInFlight = false
                }
            },
            generateVisualization: async () => {
                if (!props.isEditable || cache.generationInFlight) {
                    return
                }
                if (!values.currentTeamId) {
                    actions.generationFailed('The current project is unavailable. Refresh and try again.')
                    return
                }
                if (!props.prompt.trim()) {
                    actions.generationFailed('Add a prompt before generating the visualization.')
                    return
                }
                cache.generationInFlight = true
                const generationId = uuidv4()
                const abortController = new AbortController()
                cache.activeGenerationId = generationId
                cache.generationAbortController = abortController
                cache.disposables.add(() => () => abortController.abort(), 'generationRequest')
                actions.generationStarted()
                try {
                    actions.statusReceived(
                        await notebooksGenuiGenerate(
                            String(values.currentTeamId),
                            props.notebookShortId,
                            props.nodeId,
                            { prompt: props.prompt, generation_id: generationId, model: props.model },
                            { signal: abortController.signal }
                        )
                    )
                } catch (error) {
                    if (isCancellationError(error)) {
                        actions.generationCanceled()
                    } else {
                        const message = errorMessage(error)
                        posthog.captureException(error instanceof Error ? error : new Error(message), {
                            action: 'generate notebook visualization',
                        })
                        actions.generationFailed(message)
                    }
                } finally {
                    cache.disposables.dispose('generationRequest')
                    if (cache.activeGenerationId === generationId) {
                        cache.activeGenerationId = null
                        cache.generationAbortController = null
                    }
                    cache.generationInFlight = false
                }
            },
            loadStatus: async () => {
                if (!values.currentTeamId) {
                    return
                }
                try {
                    actions.statusReceived(
                        await notebooksGenuiStatus(String(values.currentTeamId), props.notebookShortId, props.nodeId)
                    )
                } catch (error) {
                    actions.statusFailed(errorMessage(error))
                }
            },
            statusReceived: ({ status }) => {
                cache.disposables.dispose('statusPoll')
                if (shouldPoll(status)) {
                    scheduleStatusPoll()
                }
            },
            statusFailed: () => {
                if (shouldPoll(values.status) && values.pollAttempts < STATUS_POLL_MAX_ATTEMPTS) {
                    scheduleStatusPoll()
                }
            },
        }
    }),
    afterMount(({ actions }) => actions.loadStatus()),
])
