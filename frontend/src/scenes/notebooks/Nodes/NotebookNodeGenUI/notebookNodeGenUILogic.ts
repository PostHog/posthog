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
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import { ApiError } from 'lib/api'
import { teamLogic } from 'scenes/teamLogic'

import {
    canvasesBuildsRetrieve,
    canvasesCreate,
    canvasesPartialUpdate,
    canvasesRetrieve,
} from 'products/canvas/frontend/generated/api'
import {
    BuildStatusEnumApi,
    type CanvasApi,
    type CanvasBuildApi,
    type CanvasBuildsResponseApi,
} from 'products/canvas/frontend/generated/api.schemas'
import { taskChannelsList, tasksCreate, tasksRetrieve, tasksRunCreate } from 'products/tasks/frontend/generated/api'
import { TaskExecutionModeEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { GenUICapabilities, parseGenUICapabilities } from './genUIArtifactBridge'
import { GenUIFrameSchema } from './genUIFrames'
import { GenUIGenerationProgress } from './genUIGenerationProgress'
import { buildGenUIGenerationPrompt, getGenUIName } from './genUIGenerationPrompt'

const GENERATION_POLL_INTERVAL_MS = 5000
const GENERATION_POLL_MAX_ATTEMPTS = 180

type GenerationWatch = {
    canvasId: string
    taskId: string
    initialVersionId: string | null
    attempts: number
    observedAtMs: number
}

export type NotebookNodeGenUILogicProps = {
    id: string
    nodeId: string
    channelId?: string
    prompt: string
    frames: GenUIFrameSchema[]
    missingFrames: string[]
    isEditable: boolean
    updateAttributes: (attributes: { id?: string; channelId?: string }) => void
}

export interface notebookNodeGenUILogicValues {
    currentTeamId: number | null
    artifactUrl: string | null
    builds: CanvasBuildsResponseApi | null
    buildsLoading: boolean
    canvas: CanvasApi | null
    canvasCreationError: string | null
    canvasLoading: boolean
    canvasMissing: boolean
    capabilities: GenUICapabilities | undefined
    creatingCanvas: boolean
    generationError: string | null
    generationProgress: GenUIGenerationProgress | null
    generationWatch: GenerationWatch | null
    isGenerating: boolean
    publishedBuild: CanvasBuildApi | null
    runtimeError: string | null
}

export interface notebookNodeGenUILogicActions {
    createFromPrompt: () => { value: true }
    createFromPromptFailure: (error: string) => { error: string }
    createFromPromptSuccess: (canvasId: string) => { canvasId: string }
    generationFailed: (error: string) => { error: string }
    generationProgressUpdated: (progress: GenUIGenerationProgress) => { progress: GenUIGenerationProgress }
    loadBuilds: () => any
    loadBuildsFailure: (error: string, errorObject?: any) => { error: string; errorObject?: any }
    loadBuildsSuccess: (
        builds: CanvasBuildsResponseApi,
        payload?: any
    ) => { builds: CanvasBuildsResponseApi; payload?: any }
    loadCanvas: () => any
    loadCanvasFailure: (error: string, errorObject?: any) => { error: string; errorObject?: any }
    loadCanvasSuccess: (canvas: CanvasApi, payload?: any) => { canvas: CanvasApi; payload?: any }
    pollGeneration: () => { value: true }
    setRuntimeError: (error: string | null) => { error: string | null }
    startWatching: (
        canvasId: string,
        taskId: string,
        initialVersionId: string | null
    ) => { canvasId: string; taskId: string; initialVersionId: string | null }
    stopWatching: () => { value: true }
}

export interface notebookNodeGenUILogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        artifactUrl: (publishedBuild: CanvasBuildApi | null) => string | null
        capabilities: (publishedBuild: CanvasBuildApi | null) => GenUICapabilities | undefined
        isGenerating: (generationWatch: GenerationWatch | null) => boolean
        publishedBuild: (builds: CanvasBuildsResponseApi | null) => CanvasBuildApi | null
    }
}

export type notebookNodeGenUILogicType = MakeLogicType<
    notebookNodeGenUILogicValues,
    notebookNodeGenUILogicActions,
    NotebookNodeGenUILogicProps,
    notebookNodeGenUILogicMeta
>

export const notebookNodeGenUILogic: LogicWrapper<notebookNodeGenUILogicType> = kea<notebookNodeGenUILogicType>([
    props({} as NotebookNodeGenUILogicProps),
    key((props) => props.nodeId),
    path((key) => ['scenes', 'notebooks', 'Nodes', 'notebookNodeGenUILogic', key]),
    connect(() => ({ values: [teamLogic, ['currentTeamId']] })),
    actions({
        createFromPrompt: true,
        createFromPromptSuccess: (canvasId: string) => ({ canvasId }),
        createFromPromptFailure: (error: string) => ({ error }),
        generationFailed: (error: string) => ({ error }),
        generationProgressUpdated: (progress: GenUIGenerationProgress) => ({ progress }),
        pollGeneration: true,
        setRuntimeError: (error: string | null) => ({ error }),
        startWatching: (canvasId: string, taskId: string, initialVersionId: string | null) => ({
            canvasId,
            taskId,
            initialVersionId,
        }),
        stopWatching: true,
    }),
    loaders(({ props, values }) => ({
        canvas: [
            null as CanvasApi | null,
            {
                loadCanvas: async () => await canvasesRetrieve(String(values.currentTeamId), props.id),
            },
        ],
        builds: [
            null as CanvasBuildsResponseApi | null,
            {
                loadBuilds: async () => await canvasesBuildsRetrieve(String(values.currentTeamId), props.id),
            },
        ],
    })),
    reducers({
        creatingCanvas: [
            false,
            {
                createFromPrompt: () => true,
                createFromPromptSuccess: () => false,
                createFromPromptFailure: () => false,
            },
        ],
        canvasCreationError: [
            null as string | null,
            {
                createFromPrompt: () => null,
                createFromPromptSuccess: () => null,
                createFromPromptFailure: (_, { error }) => error,
            },
        ],
        generationError: [
            null as string | null,
            {
                createFromPrompt: () => null,
                generationFailed: (_, { error }) => error,
                startWatching: () => null,
            },
        ],
        canvasMissing: [
            false,
            {
                loadCanvas: () => false,
                loadCanvasFailure: (_, { errorObject }: { errorObject?: unknown }) =>
                    errorObject instanceof ApiError && errorObject.status === 404,
                loadCanvasSuccess: () => false,
            },
        ],
        runtimeError: [
            null as string | null,
            {
                setRuntimeError: (_, { error }) => error,
            },
        ],
        generationWatch: [
            null as GenerationWatch | null,
            {
                startWatching: (_, { canvasId, taskId, initialVersionId }) => ({
                    canvasId,
                    taskId,
                    initialVersionId,
                    attempts: 0,
                    observedAtMs: Date.now(),
                }),
                pollGeneration: (state) => (state ? { ...state, attempts: state.attempts + 1 } : null),
                stopWatching: () => null,
                generationFailed: () => null,
            },
        ],
        generationProgress: [
            null as GenUIGenerationProgress | null,
            {
                startWatching: () => null,
                generationProgressUpdated: (_, { progress }) => progress,
                generationFailed: () => null,
                stopWatching: () => null,
            },
        ],
    }),
    selectors({
        publishedBuild: [
            (s) => [s.builds],
            (builds: CanvasBuildsResponseApi | null): CanvasBuildApi | null =>
                builds?.builds.find((build) => build.id === builds.published_build_id) ?? null,
        ],
        artifactUrl: [
            (s) => [s.publishedBuild],
            (publishedBuild: CanvasBuildApi | null): string | null => publishedBuild?.artifact_url ?? null,
        ],
        capabilities: [
            (s) => [s.publishedBuild],
            (publishedBuild: CanvasBuildApi | null): GenUICapabilities | undefined =>
                parseGenUICapabilities(publishedBuild?.manifest?.capabilities),
        ],
        isGenerating: [
            (s) => [s.generationWatch],
            (generationWatch: GenerationWatch | null): boolean => generationWatch !== null,
        ],
    }),
    listeners(({ actions, values, props, cache }) => ({
        createFromPrompt: async () => {
            if (!props.isEditable) {
                actions.createFromPromptFailure('You need edit access to generate this visualization.')
                return
            }
            if (cache.creatingFromPrompt) {
                return
            }
            const instruction = props.prompt.trim()
            if (!instruction) {
                actions.createFromPromptFailure('Add a prompt before generating the visualization.')
                return
            }
            if (!values.currentTeamId) {
                actions.createFromPromptFailure('The current project is unavailable. Refresh and try again.')
                return
            }

            cache.creatingFromPrompt = true
            try {
                let canvas: CanvasApi
                if (props.id) {
                    canvas = await canvasesRetrieve(String(values.currentTeamId), props.id)
                } else {
                    let channelId = props.channelId
                    if (!channelId) {
                        const channels = await taskChannelsList(String(values.currentTeamId))
                        channelId = channels.results.find((channel) => channel.channel_type === 'personal')?.id
                    }
                    if (!channelId) {
                        throw new Error("Couldn't find your personal task channel. Refresh and try again.")
                    }
                    canvas = await canvasesCreate(String(values.currentTeamId), {
                        name: getGenUIName(instruction),
                        channel_id: channelId,
                    })
                    props.updateAttributes({ id: canvas.id, channelId: canvas.channel })
                }

                const generationPrompt = buildGenUIGenerationPrompt({
                    canvasId: canvas.id,
                    name: canvas.name,
                    channelId: canvas.channel,
                    instruction,
                    frames: props.frames,
                    missingFrames: props.missingFrames,
                    isEdit: Boolean(canvas.current_version_id),
                })
                const task = await tasksCreate(String(values.currentTeamId), {
                    title: `${canvas.current_version_id ? 'Update' : 'Build'} notebook visualization "${canvas.name}"`,
                    description: generationPrompt,
                    channel: canvas.channel,
                })
                const updatedCanvas = await canvasesPartialUpdate(String(values.currentTeamId), canvas.id, {
                    context: instruction,
                    generation_task_id: task.id,
                })
                await tasksRunCreate(String(values.currentTeamId), task.id, {
                    mode: TaskExecutionModeEnumApi.Background,
                    pending_user_message: generationPrompt,
                })
                actions.loadCanvasSuccess(updatedCanvas)
                actions.createFromPromptSuccess(canvas.id)
                actions.startWatching(canvas.id, task.id, canvas.current_version_id)
                lemonToast.success('Visualization generation started')
            } catch (error) {
                const resolvedError = error instanceof Error ? error : new Error(String(error))
                posthog.captureException(resolvedError, { action: 'generate notebook visualization' })
                actions.createFromPromptFailure(resolvedError.message)
            } finally {
                cache.creatingFromPrompt = false
            }
        },
        startWatching: () => {
            cache.disposables.dispose('generationPoll')
            actions.pollGeneration()
        },
        stopWatching: () => {
            cache.disposables.dispose('generationPoll')
        },
        generationFailed: () => {
            cache.disposables.dispose('generationPoll')
        },
        pollGeneration: async () => {
            const watch = values.generationWatch
            if (!watch) {
                return
            }
            if (watch.attempts >= GENERATION_POLL_MAX_ATTEMPTS) {
                actions.generationFailed(
                    'Generation is taking longer than expected. Open the task to check its progress.'
                )
                return
            }

            try {
                const [builds, task] = await Promise.all([
                    canvasesBuildsRetrieve(String(values.currentTeamId), watch.canvasId),
                    tasksRetrieve(String(values.currentTeamId), watch.taskId),
                ])
                actions.loadBuildsSuccess(builds)
                const publishedBuild = builds.builds.find((build) => build.id === builds.published_build_id)
                const latestIsLive =
                    Boolean(builds.current_version_id) &&
                    publishedBuild?.source_version_id === builds.current_version_id
                const versionChanged = builds.current_version_id !== watch.initialVersionId
                const taskCompleted = task.latest_run?.status === 'completed'
                const currentBuild = builds.builds.find(
                    (build) => build.source_version_id === builds.current_version_id
                )
                actions.generationProgressUpdated({
                    buildStatus: versionChanged ? (currentBuild?.build_status ?? null) : null,
                    runCreatedAt: task.latest_run?.created_at ?? null,
                    runStage: task.latest_run?.stage ?? null,
                    runStatus: task.latest_run?.status ?? null,
                    runUpdatedAt: task.latest_run?.updated_at ?? null,
                })

                if (latestIsLive && (versionChanged || taskCompleted)) {
                    actions.stopWatching()
                    actions.loadCanvas()
                    lemonToast.success('Visualization ready')
                    return
                }
                if (currentBuild?.build_status === BuildStatusEnumApi.Failed) {
                    actions.generationFailed(
                        currentBuild.diagnostics.find((diagnostic) => diagnostic.severity === 'error')?.message ||
                            "Couldn't build this visualization. Try again."
                    )
                    return
                }
                if (task.latest_run?.status === 'failed' || task.latest_run?.status === 'cancelled') {
                    actions.generationFailed(
                        task.latest_run.error_message?.trim() || "Couldn't generate this visualization. Try again."
                    )
                    return
                }
                if (taskCompleted && !builds.current_version_id) {
                    actions.generationFailed(
                        'The generation task finished without publishing a visualization. Try again.'
                    )
                    return
                }
                if (taskCompleted && !versionChanged) {
                    actions.generationFailed(
                        'The generation task finished without publishing a new visualization. Try again.'
                    )
                    return
                }
            } catch {
                if (!values.generationWatch) {
                    return
                }
            }

            cache.disposables.add(() => {
                const timeoutId = setTimeout(() => actions.pollGeneration(), GENERATION_POLL_INTERVAL_MS)
                return () => clearTimeout(timeoutId)
            }, 'generationPoll')
        },
        loadCanvasSuccess: ({ canvas }) => {
            if (canvas.generation_task_id && !values.generationWatch) {
                actions.startWatching(canvas.id, canvas.generation_task_id, canvas.current_version_id)
            }
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.id) {
            actions.loadCanvas()
            actions.loadBuilds()
        } else if (props.isEditable && props.prompt.trim()) {
            actions.createFromPrompt()
        }
    }),
    propsChanged(({ actions, props }, oldProps) => {
        if (props.id && props.id !== oldProps.id) {
            actions.loadCanvas()
            actions.loadBuilds()
        }
    }),
])
