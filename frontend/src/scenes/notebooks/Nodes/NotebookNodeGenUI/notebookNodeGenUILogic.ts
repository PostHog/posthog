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
    selectors,
} from 'kea'
import posthog from 'posthog-js'
import { v4 as uuidv4 } from 'uuid'

import { ApiError } from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import {
    notebooksGenuiCancel,
    notebooksGenuiFrame,
    notebooksGenuiGenerate,
    notebooksGenuiRevert,
    notebooksGenuiSaveSource,
    notebooksGenuiSource,
    notebooksGenuiStatus,
} from 'products/notebooks/frontend/generated/api'
import type {
    GenUIFrameApi,
    GenUISourceResponseApi,
    GenUIStatusApi,
    GenUIVersionApi,
} from 'products/notebooks/frontend/generated/api.schemas'

import { DEFAULT_GENUI_MODEL, GENUI_MODEL_INFO, type GenUIModel, isGenUIModel } from './genUIModels'

const STATUS_POLL_INTERVAL_MS = 1_000

export type GenUIGenerationOperation = 'initial' | 'regenerate' | 'improve'
export type GenUIGenerationModalOperation = Exclude<GenUIGenerationOperation, 'initial'> | null

export type GenUIWorkingStatus = {
    detail: string
    isOverEstimate: boolean
    label: string
    timing: string
}

export type NotebookNodeGenUILogicProps = {
    notebookShortId: string
    nodeId: string
    prompt: string
    model: GenUIModel
    isEditable: boolean
    persistNotebook: () => Promise<void>
}

export interface notebookNodeGenUILogicValues {
    activeGenerationModel: GenUIModel
    currentTeamId: number | null
    cancellationInFlight: boolean
    elapsedSeconds: number
    error: string | null
    frameRevision: number
    generationDraftModel: GenUIModel
    generationDraftPrompt: string
    generationInFlight: boolean
    generationModalOperation: GenUIGenerationModalOperation
    isWorking: boolean
    restoreInFlight: boolean
    runtimeError: string | null
    selectedVersion: GenUIVersionApi | null
    selectedVersionId: string | null
    sourceDraft: string
    sourceError: string | null
    sourceLoading: boolean
    sourceModalOpen: boolean
    sourceNote: string
    sourceSaving: boolean
    status: GenUIStatusApi | null
    statusLoading: boolean
    workingStatus: GenUIWorkingStatus | null
}

export interface notebookNodeGenUILogicActions {
    cancelGeneration: () => { value: true }
    cancellationFailed: (error: string) => { error: string }
    cancellationStarted: () => { value: true }
    closeGenerationModal: () => { value: true }
    closeSourceEditor: () => { value: true }
    generateVisualization: (
        prompt: string,
        model: GenUIModel,
        operation: GenUIGenerationOperation
    ) => { prompt: string; model: GenUIModel; operation: GenUIGenerationOperation }
    generationCanceled: () => { value: true }
    generationFailed: (error: string) => { error: string }
    generationFinished: () => { value: true }
    generationStarted: (startedAt: number) => { startedAt: number }
    loadStatus: () => { value: true }
    openGenerationModal: (operation: Exclude<GenUIGenerationOperation, 'initial'>) => {
        operation: 'regenerate' | 'improve'
    }
    openSourceEditor: () => { value: true }
    refreshData: () => { value: true }
    restoreFailed: (error: string) => { error: string }
    restoreSelectedVersion: () => { value: true }
    restoreStarted: () => { value: true }
    saveSource: () => { value: true }
    selectVersion: (versionId: string) => { versionId: string }
    setGenerationDraftModel: (model: GenUIModel) => { model: GenUIModel }
    setGenerationDraftPrompt: (prompt: string) => { prompt: string }
    setRuntimeError: (error: string | null) => { error: string | null }
    setSourceDraft: (source: string) => { source: string }
    setSourceNote: (note: string) => { note: string }
    sourceFailed: (error: string) => { error: string }
    sourceLoadStarted: () => { value: true }
    sourceReceived: (source: GenUISourceResponseApi) => { source: GenUISourceResponseApi }
    sourceSaveStarted: () => { value: true }
    sourceSaved: () => { value: true }
    statusFailed: (error: string) => { error: string }
    statusReceived: (status: GenUIStatusApi) => { status: GenUIStatusApi }
    tickElapsed: (elapsedSeconds: number) => { elapsedSeconds: number }
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

function isMissingNodeError(error: unknown): boolean {
    if (error instanceof ApiError) {
        const response = error.data as { code?: unknown } | undefined
        return error.code === 'node_not_found' || response?.code === 'node_not_found'
    }
    return false
}

function shouldPoll(status: GenUIStatusApi | null): boolean {
    return status?.lifecycle_status === 'generating' || status?.lifecycle_status === 'building'
}

export function formatGenUIElapsed(elapsedSeconds: number): string {
    const minutes = Math.floor(elapsedSeconds / 60)
    const seconds = elapsedSeconds % 60
    return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

export function getGenUIWorkingStatus({
    elapsedSeconds,
    hasVersions,
    isModelGenerating,
    model,
}: {
    elapsedSeconds: number
    hasVersions: boolean
    isModelGenerating: boolean
    model: GenUIModel
}): GenUIWorkingStatus {
    if (!isModelGenerating) {
        return {
            detail: 'The source is ready. Building the interactive preview.',
            isOverEstimate: false,
            label: hasVersions ? 'Building new version…' : 'Building visualization…',
            timing: 'The preview build usually takes less than a minute.',
        }
    }

    const modelInfo = GENUI_MODEL_INFO[model]
    const secondsFromEstimate = elapsedSeconds - modelInfo.estimatedSeconds
    const isOverEstimate = secondsFromEstimate > 0
    return {
        detail: `${modelInfo.name} is generating the visualization source.`,
        isOverEstimate,
        label: hasVersions ? 'Regenerating visualization…' : 'Generating visualization…',
        timing: isOverEstimate
            ? `Typical: ${modelInfo.estimateLabel} · ${formatGenUIElapsed(secondsFromEstimate)} longer than usual. The request is still active.`
            : `Typical: ${modelInfo.estimateLabel} · Estimated remaining: ${formatGenUIElapsed(
                  modelInfo.estimatedSeconds - elapsedSeconds
              )}`,
    }
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
        closeGenerationModal: true,
        closeSourceEditor: true,
        generateVisualization: (prompt: string, model: GenUIModel, operation: GenUIGenerationOperation) => ({
            prompt,
            model,
            operation,
        }),
        generationCanceled: true,
        generationFailed: (error: string) => ({ error }),
        generationFinished: true,
        generationStarted: (startedAt: number) => ({ startedAt }),
        loadStatus: true,
        openGenerationModal: (operation: Exclude<GenUIGenerationOperation, 'initial'>) => ({ operation }),
        openSourceEditor: true,
        refreshData: true,
        restoreFailed: (error: string) => ({ error }),
        restoreSelectedVersion: true,
        restoreStarted: true,
        saveSource: true,
        selectVersion: (versionId: string) => ({ versionId }),
        setGenerationDraftModel: (model: GenUIModel) => ({ model }),
        setGenerationDraftPrompt: (prompt: string) => ({ prompt }),
        setRuntimeError: (error: string | null) => ({ error }),
        setSourceDraft: (source: string) => ({ source }),
        setSourceNote: (note: string) => ({ note }),
        sourceFailed: (error: string) => ({ error }),
        sourceLoadStarted: true,
        sourceReceived: (source: GenUISourceResponseApi) => ({ source }),
        sourceSaveStarted: true,
        sourceSaved: true,
        statusFailed: (error: string) => ({ error }),
        statusReceived: (status: GenUIStatusApi) => ({ status }),
        tickElapsed: (elapsedSeconds: number) => ({ elapsedSeconds }),
    }),
    reducers(({ props }) => ({
        activeGenerationModel: [
            props.model,
            {
                generateVisualization: (_, { model }) => model,
                statusReceived: (activeModel, { status }) => {
                    const currentVersion = status.versions.find((version) => version.id === status.current_version_id)
                    return isGenUIModel(currentVersion?.model) ? currentVersion.model : activeModel
                },
            },
        ],
        cancellationInFlight: [
            false,
            {
                cancellationStarted: () => true,
                cancellationFailed: () => false,
                generationCanceled: () => false,
            },
        ],
        elapsedSeconds: [
            0,
            {
                generationStarted: () => 0,
                tickElapsed: (_, { elapsedSeconds }) => elapsedSeconds,
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
                generationFinished: () => false,
            },
        ],
        generationModalOperation: [
            null as GenUIGenerationModalOperation,
            {
                closeGenerationModal: () => null,
                openGenerationModal: (_, { operation }) => operation,
            },
        ],
        generationDraftPrompt: [
            '',
            {
                setGenerationDraftPrompt: (_, { prompt }) => prompt,
            },
        ],
        generationDraftModel: [
            DEFAULT_GENUI_MODEL,
            {
                setGenerationDraftModel: (_, { model }) => model,
            },
        ],
        error: [
            null as string | null,
            {
                generationStarted: () => null,
                cancellationFailed: (_, { error }) => error,
                generationCanceled: () => null,
                generationFailed: (_, { error }) => error,
                restoreFailed: (_, { error }) => error,
                restoreStarted: () => null,
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
                sourceSaved: (revision) => revision + 1,
            },
        ],
        selectedVersionId: [
            null as string | null,
            {
                selectVersion: (_, { versionId }) => versionId,
                statusReceived: (selectedVersionId, { status }) =>
                    selectedVersionId && status.versions.some((version) => version.id === selectedVersionId)
                        ? selectedVersionId
                        : status.current_version_id,
            },
        ],
        restoreInFlight: [
            false,
            {
                restoreStarted: () => true,
                restoreFailed: () => false,
                statusReceived: () => false,
            },
        ],
        sourceModalOpen: [
            false,
            {
                openSourceEditor: () => true,
                closeSourceEditor: () => false,
            },
        ],
        sourceLoading: [
            false,
            {
                sourceLoadStarted: () => true,
                sourceFailed: () => false,
                sourceReceived: () => false,
            },
        ],
        sourceSaving: [
            false,
            {
                sourceSaveStarted: () => true,
                sourceFailed: () => false,
                sourceSaved: () => false,
            },
        ],
        sourceError: [
            null as string | null,
            {
                sourceLoadStarted: () => null,
                sourceSaveStarted: () => null,
                sourceFailed: (_, { error }) => error,
                sourceReceived: () => null,
            },
        ],
        sourceDraft: [
            '',
            {
                setSourceDraft: (_, { source }) => source,
                sourceLoadStarted: () => '',
                sourceReceived: (_, { source }) => source.source,
            },
        ],
        sourceNote: [
            '',
            {
                closeSourceEditor: () => '',
                setSourceNote: (_, { note }) => note,
                sourceReceived: () => '',
            },
        ],
    })),
    selectors({
        selectedVersion: [
            (selectors) => [selectors.status, selectors.selectedVersionId],
            (status: GenUIStatusApi | null, selectedVersionId: string | null): GenUIVersionApi | null =>
                status?.versions.find((version) => version.id === selectedVersionId) ?? null,
        ],
        isWorking: [
            (selectors) => [selectors.generationInFlight, selectors.status],
            (generationInFlight, status): boolean => generationInFlight || shouldPoll(status),
        ],
        workingStatus: [
            (selectors) => [
                selectors.activeGenerationModel,
                selectors.elapsedSeconds,
                selectors.generationInFlight,
                selectors.status,
            ],
            (activeGenerationModel, elapsedSeconds, generationInFlight, status): GenUIWorkingStatus | null => {
                const isModelGenerating = generationInFlight || status?.lifecycle_status === 'generating'
                if (!isModelGenerating && status?.lifecycle_status !== 'building') {
                    return null
                }
                return getGenUIWorkingStatus({
                    elapsedSeconds,
                    hasVersions: Boolean(status?.versions.length),
                    isModelGenerating,
                    model: activeGenerationModel,
                })
            },
        ],
    }),
    listeners(({ actions, values, props, cache }) => {
        const scheduleStatusPoll = (): void => {
            cache.disposables.dispose('statusPoll')
            cache.disposables.add(() => {
                const timeoutId = window.setTimeout(() => actions.loadStatus(), STATUS_POLL_INTERVAL_MS)
                return () => window.clearTimeout(timeoutId)
            }, 'statusPoll')
        }

        const startElapsedClock = (startedAt: number): void => {
            cache.generationStartedAt = startedAt
            cache.disposables.dispose('elapsedClock')
            const updateElapsed = (): void => {
                actions.tickElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1_000)))
            }
            updateElapsed()
            cache.disposables.add(() => {
                const intervalId = window.setInterval(updateElapsed, 1_000)
                return () => window.clearInterval(intervalId)
            }, 'elapsedClock')
        }

        return {
            cancelGeneration: async () => {
                const generationId = cache.activeGenerationId ?? values.status?.generation_id
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
                    actions.loadStatus()
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
            generateVisualization: async ({ prompt, model, operation }) => {
                if (!props.isEditable || cache.generationInFlight) {
                    return
                }
                if (!values.currentTeamId) {
                    actions.generationFailed('The current project is unavailable. Refresh and try again.')
                    return
                }
                if (!prompt.trim()) {
                    actions.generationFailed(
                        operation === 'improve'
                            ? 'Describe the change you want to make.'
                            : 'Add a prompt before generating the visualization.'
                    )
                    return
                }
                cache.generationInFlight = true
                const generationId = uuidv4()
                const abortController = new AbortController()
                cache.activeGenerationId = generationId
                cache.generationAbortController = abortController
                cache.disposables.add(() => () => abortController.abort(), 'generationRequest', {
                    pauseOnPageHidden: false,
                })
                actions.closeGenerationModal()
                actions.generationStarted(Date.now())
                try {
                    const requestGeneration = async (): Promise<GenUIStatusApi> =>
                        await notebooksGenuiGenerate(
                            String(values.currentTeamId),
                            props.notebookShortId,
                            props.nodeId,
                            { prompt, generation_id: generationId, model, operation },
                            { signal: abortController.signal }
                        )

                    let generatedStatus: GenUIStatusApi
                    try {
                        generatedStatus = await requestGeneration()
                    } catch (error) {
                        if (!isMissingNodeError(error)) {
                            throw error
                        }
                        await props.persistNotebook()
                        generatedStatus = await requestGeneration()
                    }
                    actions.statusReceived(generatedStatus)
                    if (generatedStatus.current_version_id) {
                        actions.selectVersion(generatedStatus.current_version_id)
                    }
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
                    actions.generationFinished()
                }
            },
            generationStarted: ({ startedAt }) => startElapsedClock(startedAt),
            generationFinished: () => {
                if (!shouldPoll(values.status)) {
                    cache.disposables.dispose('elapsedClock')
                    cache.generationStartedAt = null
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
            openGenerationModal: ({ operation }) => {
                actions.setGenerationDraftPrompt(
                    operation === 'regenerate' ? (values.selectedVersion?.effective_prompt ?? '') : ''
                )
                const selectedModel = values.selectedVersion?.model
                actions.setGenerationDraftModel(isGenUIModel(selectedModel) ? selectedModel : props.model)
            },
            openSourceEditor: async () => {
                if (!values.currentTeamId || !values.selectedVersionId) {
                    return
                }
                actions.sourceLoadStarted()
                try {
                    actions.sourceReceived(
                        await notebooksGenuiSource(String(values.currentTeamId), props.notebookShortId, props.nodeId, {
                            version_id: values.selectedVersionId,
                        })
                    )
                } catch (error) {
                    actions.sourceFailed(errorMessage(error))
                }
            },
            restoreSelectedVersion: async () => {
                if (
                    !props.isEditable ||
                    !values.currentTeamId ||
                    !values.selectedVersionId ||
                    !values.status?.current_version_id ||
                    values.selectedVersionId === values.status.current_version_id ||
                    values.restoreInFlight
                ) {
                    return
                }
                actions.restoreStarted()
                try {
                    const restoredStatus = await notebooksGenuiRevert(
                        String(values.currentTeamId),
                        props.notebookShortId,
                        props.nodeId,
                        {
                            version_id: values.selectedVersionId,
                            expected_current_version_id: values.status.current_version_id,
                        }
                    )
                    actions.statusReceived(restoredStatus)
                    if (restoredStatus.current_version_id) {
                        actions.selectVersion(restoredStatus.current_version_id)
                    }
                    actions.refreshData()
                } catch (error) {
                    actions.restoreFailed(errorMessage(error))
                }
            },
            saveSource: async () => {
                if (
                    !props.isEditable ||
                    !values.currentTeamId ||
                    !values.status?.current_version_id ||
                    values.selectedVersionId !== values.status.current_version_id ||
                    !values.sourceDraft.trim() ||
                    values.sourceSaving
                ) {
                    return
                }
                actions.sourceSaveStarted()
                try {
                    const savedStatus = await notebooksGenuiSaveSource(
                        String(values.currentTeamId),
                        props.notebookShortId,
                        props.nodeId,
                        {
                            source: values.sourceDraft,
                            prompt: values.sourceNote,
                            expected_current_version_id: values.status.current_version_id,
                        }
                    )
                    actions.statusReceived(savedStatus)
                    if (savedStatus.current_version_id) {
                        actions.selectVersion(savedStatus.current_version_id)
                    }
                    actions.sourceSaved()
                    actions.closeSourceEditor()
                } catch (error) {
                    actions.sourceFailed(errorMessage(error))
                }
            },
            statusReceived: ({ status }) => {
                cache.disposables.dispose('statusPoll')
                if (shouldPoll(status)) {
                    scheduleStatusPoll()
                    const serverStartedAt = status.generation_started_at
                        ? new Date(status.generation_started_at).getTime()
                        : null
                    if (serverStartedAt && serverStartedAt !== cache.generationStartedAt) {
                        startElapsedClock(serverStartedAt)
                    } else if (!cache.generationStartedAt) {
                        startElapsedClock(Date.now())
                    }
                } else if (!cache.generationInFlight) {
                    cache.disposables.dispose('elapsedClock')
                    cache.generationStartedAt = null
                }
            },
            statusFailed: () => {
                if (shouldPoll(values.status)) {
                    scheduleStatusPoll()
                }
            },
        }
    }),
    afterMount(({ actions }) => actions.loadStatus()),
])
