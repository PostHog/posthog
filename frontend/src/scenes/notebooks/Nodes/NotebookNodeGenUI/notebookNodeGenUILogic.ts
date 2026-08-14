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
    propsChanged,
    reducers,
    selectors,
} from 'kea'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import {
    NotebookDependencyChainStatus,
    notebookNodeStalenessLogic,
} from 'scenes/notebooks/Notebook/notebookNodeStalenessLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    notebooksGenuiEnsure,
    notebooksGenuiFrame,
    notebooksGenuiRegenerate,
    notebooksGenuiRetry,
    notebooksGenuiRun,
    notebooksGenuiStatus,
} from 'products/notebooks/frontend/generated/api'
import type { GenUIFrameApi, GenUIStatusApi } from 'products/notebooks/frontend/generated/api.schemas'

const STATUS_POLL_INTERVAL_MS = 3000
const STATUS_POLL_MAX_ATTEMPTS = 600

type GenUIRefreshIntent = 'ensure' | 'regenerate' | 'retry' | 'run'

export type NotebookNodeGenUILogicProps = {
    notebookShortId: string
    nodeId: string
    legacyCanvasId?: string
    prompt: string
    inputs: string[]
    serializedInputs: string
    persistedInputs: string
    inputValidationError: string | null
    isEditable: boolean
    getContent: () => JSONContent | null
    updateAttributes: (attributes: { inputs?: string }) => void
}

export interface notebookNodeGenUILogicValues {
    currentTeamId: number | null
    error: string | null
    isGenerating: boolean
    isRefreshingInputs: boolean
    mutationInFlight: boolean
    pollAttempts: number
    runtimeError: string | null
    status: GenUIStatusApi | null
    statusLoading: boolean
}

export interface notebookNodeGenUILogicActions {
    clearNodeStale: (nodeId: string) => { nodeId: string }
    dependencyChainFinished: (
        targetNodeId: string,
        status: NotebookDependencyChainStatus
    ) => { targetNodeId: string; status: NotebookDependencyChainStatus }
    ensureVisualization: () => { value: true }
    inputRefreshFinished: () => { value: true }
    inputRefreshStarted: () => { value: true }
    loadStatus: () => { value: true }
    mutationFailed: (error: string) => { error: string }
    mutationStarted: () => { value: true }
    reportRenderFailure: (reason: string) => { reason: string }
    reportRenderSuccess: () => { value: true }
    regenerateVisualization: () => { value: true }
    retryVisualization: () => { value: true }
    runDependencyChain: (
        content: JSONContent | null,
        targetNodeId: string
    ) => { content: JSONContent | null; targetNodeId: string }
    runVisualization: () => { value: true }
    setRuntimeError: (error: string | null) => { error: string | null }
    statusFailed: (error: string) => { error: string }
    statusReceived: (status: GenUIStatusApi) => { status: GenUIStatusApi }
}

export interface notebookNodeGenUILogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        isGenerating: (status: GenUIStatusApi | null) => boolean
    }
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
    return error instanceof Error ? error.message : String(error)
}

function shouldPoll(status: GenUIStatusApi | null): boolean {
    return status?.lifecycle_status === 'generating' || status?.lifecycle_status === 'building'
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
    connect((props: NotebookNodeGenUILogicProps) => ({
        values: [teamLogic, ['currentTeamId']],
        actions: [
            notebookNodeStalenessLogic({ shortId: props.notebookShortId }),
            ['clearNodeStale', 'dependencyChainFinished', 'runDependencyChain'],
        ],
    })),
    actions({
        ensureVisualization: true,
        inputRefreshFinished: true,
        inputRefreshStarted: true,
        loadStatus: true,
        mutationFailed: (error: string) => ({ error }),
        mutationStarted: true,
        reportRenderFailure: (reason: string) => ({ reason }),
        reportRenderSuccess: true,
        regenerateVisualization: true,
        retryVisualization: true,
        runVisualization: true,
        setRuntimeError: (error: string | null) => ({ error }),
        statusFailed: (error: string) => ({ error }),
        statusReceived: (status: GenUIStatusApi) => ({ status }),
    }),
    reducers({
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
                statusReceived: () => false,
                statusFailed: () => false,
            },
        ],
        mutationInFlight: [
            false,
            {
                mutationStarted: () => true,
                statusReceived: () => false,
                mutationFailed: () => false,
            },
        ],
        isRefreshingInputs: [
            false,
            {
                inputRefreshStarted: () => true,
                inputRefreshFinished: () => false,
                mutationFailed: () => false,
            },
        ],
        error: [
            null as string | null,
            {
                mutationStarted: () => null,
                statusReceived: () => null,
                mutationFailed: (_, { error }) => error,
                statusFailed: (_, { error }) => error,
            },
        ],
        runtimeError: [
            null as string | null,
            {
                setRuntimeError: (_, { error }) => error,
            },
        ],
        pollAttempts: [
            0,
            {
                statusReceived: (attempts, { status }) => (shouldPoll(status) ? attempts + 1 : 0),
                statusFailed: (attempts) => attempts + 1,
                mutationStarted: () => 0,
            },
        ],
    }),
    selectors({
        isGenerating: [(s) => [s.status], (status: GenUIStatusApi | null): boolean => shouldPoll(status)],
    }),
    listeners(({ actions, values, props, cache }) => {
        const requestBody = (): { prompt: string; inputs: string[]; legacy_canvas_id?: string } => ({
            prompt: props.prompt,
            inputs: props.inputs,
            ...(props.legacyCanvasId ? { legacy_canvas_id: props.legacyCanvasId } : {}),
        })
        const requireRequest = (): { projectId: string } | null => {
            if (!values.currentTeamId) {
                actions.mutationFailed('The current project is unavailable. Refresh and try again.')
                return null
            }
            if (props.inputValidationError) {
                actions.mutationFailed(props.inputValidationError)
                return null
            }
            if (!props.prompt.trim()) {
                actions.mutationFailed('Add a prompt before generating the visualization.')
                return null
            }
            return { projectId: String(values.currentTeamId) }
        }
        const completeMutation = async (request: () => Promise<GenUIStatusApi>): Promise<GenUIStatusApi | null> => {
            if (cache.mutationInFlight) {
                return null
            }
            cache.mutationInFlight = true
            actions.mutationStarted()
            try {
                const status = await request()
                actions.statusReceived(status)
                return status
            } catch (error) {
                const message = errorMessage(error)
                posthog.captureException(error instanceof Error ? error : new Error(message), {
                    action: 'update notebook visualization',
                })
                actions.mutationFailed(message)
                return null
            } finally {
                cache.mutationInFlight = false
            }
        }
        const startInputRefresh = (intent: GenUIRefreshIntent): void => {
            if (cache.inputRefreshIntent) {
                return
            }
            const content = props.getContent()
            if (!content) {
                actions.mutationFailed('The notebook content is unavailable. Refresh and try again.')
                return
            }
            cache.inputRefreshIntent = intent
            actions.inputRefreshStarted()
            actions.runDependencyChain(content, props.nodeId)
        }
        const performIntent = async (intent: GenUIRefreshIntent, allowInputRefresh = true): Promise<void> => {
            if (allowInputRefresh && values.status?.input_states.some((input) => input.input_status !== 'ready')) {
                startInputRefresh(intent)
                return
            }

            let response: GenUIStatusApi | null = null
            if (intent === 'ensure' || intent === 'regenerate') {
                const request = requireRequest()
                if (!request) {
                    return
                }
                response = await completeMutation(() =>
                    intent === 'ensure'
                        ? notebooksGenuiEnsure(request.projectId, props.notebookShortId, props.nodeId, requestBody())
                        : notebooksGenuiRegenerate(
                              request.projectId,
                              props.notebookShortId,
                              props.nodeId,
                              requestBody()
                          )
                )
            } else if (values.currentTeamId) {
                response = await completeMutation(() =>
                    intent === 'retry'
                        ? notebooksGenuiRetry(String(values.currentTeamId), props.notebookShortId, props.nodeId)
                        : notebooksGenuiRun(String(values.currentTeamId), props.notebookShortId, props.nodeId)
                )
            }

            if (response?.lifecycle_status === 'awaiting_inputs') {
                if (allowInputRefresh) {
                    startInputRefresh(intent)
                } else {
                    actions.mutationFailed(
                        'The dataframe cells finished, but their saved previews are not ready yet. Try again.'
                    )
                }
                return
            }
            if (response && intent === 'regenerate') {
                lemonToast.success('Visualization regeneration started')
            } else if (response && intent === 'run') {
                lemonToast.success('Visualization data refreshed')
            }
        }
        const scheduleStatusPoll = (): void => {
            cache.disposables.dispose('statusPoll')
            if (values.pollAttempts >= STATUS_POLL_MAX_ATTEMPTS) {
                if (!values.error) {
                    actions.statusFailed('Generation is taking longer than expected. Open the task to check progress.')
                }
                return
            }
            cache.disposables.add(() => {
                const timeoutId = window.setTimeout(() => actions.loadStatus(), STATUS_POLL_INTERVAL_MS)
                return () => window.clearTimeout(timeoutId)
            }, 'statusPoll')
        }

        return {
            ensureVisualization: async () => {
                if (!props.isEditable) {
                    return
                }
                await performIntent('ensure')
            },
            regenerateVisualization: async () => {
                if (!props.isEditable) {
                    return
                }
                await performIntent('regenerate')
            },
            retryVisualization: async () => {
                if (!props.isEditable || !values.currentTeamId) {
                    return
                }
                await performIntent('retry')
            },
            runVisualization: async () => {
                if (!props.isEditable || !values.currentTeamId) {
                    return
                }
                await performIntent('run')
            },
            dependencyChainFinished: async ({ targetNodeId, status }) => {
                if (targetNodeId !== props.nodeId || !cache.inputRefreshIntent) {
                    return
                }
                const intent = cache.inputRefreshIntent as GenUIRefreshIntent
                cache.inputRefreshIntent = null
                actions.inputRefreshFinished()
                if (status !== 'done') {
                    actions.mutationFailed(
                        'Could not refresh the required dataframe cells. Check their errors and try again.'
                    )
                    return
                }
                await performIntent(intent, false)
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
            reportRenderFailure: ({ reason }) => {
                posthog.capture('notebook genui render failed', {
                    reason,
                    lifecycle_status: values.status?.lifecycle_status,
                    dependency_count: values.status?.input_states.length ?? 0,
                    truncated: values.status?.input_states.some((input) => input.truncated === true) ?? false,
                })
            },
            reportRenderSuccess: () => {
                posthog.capture('notebook genui rendered', {
                    lifecycle_status: values.status?.lifecycle_status,
                    dependency_count: values.status?.input_states.length ?? 0,
                    truncated: values.status?.input_states.some((input) => input.truncated === true) ?? false,
                })
            },
            statusReceived: ({ status }) => {
                if (status.lifecycle_status === 'ready') {
                    actions.clearNodeStale(props.nodeId)
                }
                cache.disposables.dispose('statusPoll')
                if (shouldPoll(status)) {
                    scheduleStatusPoll()
                }
            },
            statusFailed: () => {
                if (shouldPoll(values.status)) {
                    scheduleStatusPoll()
                }
            },
        }
    }),
    afterMount(({ actions, props }) => {
        if (props.isEditable && props.persistedInputs !== props.serializedInputs) {
            props.updateAttributes({ inputs: props.serializedInputs })
            return
        }
        if (!props.isEditable) {
            actions.loadStatus()
        } else if (props.prompt.trim() && !props.inputValidationError) {
            actions.ensureVisualization()
        }
    }),
    propsChanged(({ actions, props, values }, oldProps) => {
        if (props.isEditable && props.persistedInputs !== props.serializedInputs) {
            props.updateAttributes({ inputs: props.serializedInputs })
            return
        }
        const inferredInputsWerePersisted =
            oldProps.persistedInputs !== oldProps.serializedInputs && props.persistedInputs === props.serializedInputs
        const definitionChanged =
            props.prompt !== oldProps.prompt || props.inputs.join('\0') !== oldProps.inputs.join('\0')
        if (
            (definitionChanged || inferredInputsWerePersisted) &&
            props.prompt.trim() &&
            !props.inputValidationError &&
            (values.status || inferredInputsWerePersisted)
        ) {
            actions.ensureVisualization()
        }
    }),
])
