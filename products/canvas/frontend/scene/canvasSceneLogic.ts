import {
    MakeLogicType,
    actions,
    afterMount,
    beforeUnmount,
    connect,
    getContext,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import { toast } from '@posthog/quill'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { projectLogic } from 'scenes/projectLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { todayViewsLogic } from '~/layout/today/todayViewsLogic'
import { Breadcrumb, SidePanelTab, UserType } from '~/types'

import { runStreamLogic } from 'products/posthog_ai/frontend/api/logics'

import { CANVAS_EVENTS, CanvasSurface, captureCanvasAction } from '../canvasAnalytics'
import {
    CanvasGenerationTask,
    CanvasSpace,
    canvasSpaceLabel,
    isStartingRunStatus,
    isTerminalRunStatus,
    loadCanvasGenerationTask,
    loadCanvasSpace,
    loadCanvasSpaces,
    CanvasTaskMove,
    moveCanvasTasks,
    ownCanvasTaskIds,
    partialMoveMessage,
    restoreCanvasTasks,
} from '../canvasTasksApi'
import { CanvasVisibility, canvasVisibility, visibilitySpace } from '../canvasVisibility'
import {
    canvasesBuildActionCreate,
    canvasesBuildsRetrieve,
    canvasesPartialUpdate,
    canvasesRequestFixCreate,
    canvasesViewRetrieve,
} from '../generated/api'
import type {
    CanvasApi,
    CanvasSourceProjectApi,
    CanvasBuildActionActionEnumApi,
    CanvasBuildApi,
    CanvasBuildsResponseApi,
    CanvasFixRequestResultApi,
    CanvasViewResponseApi,
} from '../generated/api.schemas'
import { CanvasStartHandoff, canvasNewLogic } from '../newCanvas/canvasNewLogic'
import { canvasPanelTab } from '../sidePanel/canvasPanelTabs'
import { canvasSidePanelLogic } from '../sidePanel/canvasSidePanelLogic'
import { startCanvasGeneration } from '../startCanvasGeneration'
import { deleteCanvasWithUndo } from './deleteCanvasWithUndo'

// pinned: the path of the single-file component a draft renders, shared with PostHog Desktop
export const CANVAS_COMPONENT_PATH = 'src/canvas.tsx'
const POLL_INTERVAL_MS = 3000

export interface CanvasSceneLogicProps {
    id: string
}

/** What the canvas body shows. Each value is a distinct screen. */
export type CanvasBodyState =
    | 'loading'
    | 'error'
    | 'missing'
    | 'empty'
    | 'generating'
    | 'generation-ended'
    | 'built'
    | 'draft'
    | 'draft-unavailable'

export type CanvasBuildStatus = 'none' | 'building' | 'failed' | 'live'

/** Where a generation run is: its task exists but the agent has not begun, or the agent is working. */
export type CanvasGenerationPhase = 'starting' | 'running'

/** What a canvas frame renders: a build when one is ready, else single-file source in the draft sandbox. */
export interface CanvasRenderSource {
    /** The source version the running code came from. */
    sourceVersionId: string | null
    build: CanvasBuildApi | null
    draftSource: CanvasSourceProjectApi | null
}

/** Whether the agent is working a turn of a run, as its session stream last said. */
export interface CanvasAgentTurn {
    runId: string
    /** Null while the stream cannot tell, so the run status decides. */
    active: boolean | null
}

/** Tabs the canvas scene does not show. Support and exports still open over the canvas tabs when asked for. */
function replacedByCanvasTabs(tab: SidePanelTab): boolean {
    return !canvasPanelTab(tab) && tab !== SidePanelTab.Support && tab !== SidePanelTab.Exports
}

/** A cloud run stays open after the agent's turn, so its stream, not its status, says when the agent stops. */
function readAgentTurn(stream: ReturnType<typeof runStreamLogic.build>): boolean | null {
    const { historyComplete, sseStatus, isThinking } = stream.values
    return historyComplete && sseStatus !== 'error' ? isThinking : null
}

export interface CanvasFixRequest {
    buildId: string
    /** The runtime error's class name. Omitted for a failed build, whose diagnostics the server reads. */
    errorType?: string
}

export function canvasBuildStatus(
    builds: CanvasBuildsResponseApi | null,
    view: CanvasViewResponseApi | null
): CanvasBuildStatus {
    const list = builds?.builds ?? []
    if (list.some((build) => build.build_status === 'queued' || build.build_status === 'building')) {
        return 'building'
    }
    if (!builds && view?.has_active_build) {
        return 'building'
    }
    const currentVersionId = builds?.current_version_id ?? view?.current_version_id ?? null
    const newestForHead = list.find((build) => build.source_version_id === currentVersionId)
    if (newestForHead?.build_status === 'failed') {
        return 'failed'
    }
    if (builds?.published_build_id ?? view?.canvas.published_build_id) {
        return 'live'
    }
    return 'none'
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface canvasSceneLogicValues {
    startHandoff: CanvasStartHandoff | null // canvasNewLogic
    blocksCanvasId: string | null // canvasSidePanelLogic
    currentProjectId: number | null // projectLogic
    selectedTab: SidePanelTab | null // sidePanelStateLogic
    sidePanelOpen: boolean // sidePanelStateLogic
    user: UserType | null // userLogic
    agentTurn: CanvasAgentTurn | null
    bodyState: CanvasBodyState
    breadcrumbs: Breadcrumb[]
    buildActionPending: boolean
    buildStatus: CanvasBuildStatus
    builds: CanvasBuildsResponseApi | null
    buildsLoading: boolean
    busy: boolean
    canvas: CanvasApi | null
    draftCode: string | null
    fixRequestPending: boolean
    fixTaskId: string | null
    generationError: string | null
    generationPhase: CanvasGenerationPhase | null
    generationStarting: boolean
    generationTask: CanvasGenerationTask | null
    generationTaskLoading: boolean
    instruction: string
    instructionFromSuggestion: boolean
    isCreator: boolean
    isGenerating: boolean
    liveBuild: CanvasBuildApi | null
    liveRenderSource: CanvasRenderSource
    makePublicOpen: boolean
    runtimeError: string | null
    sandboxDocumentUrl: string | null
    shouldPoll: boolean
    sidePanelAvailable: boolean
    sidePanelContext: SidePanelSceneContext
    space: CanvasSpace | null
    spaceLoading: boolean
    view: CanvasViewResponseApi | null
    viewLoading: boolean
    viewMissing: boolean
    viewUnavailable: boolean
    visibility: CanvasVisibility | null
    visibilityChanging: boolean
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface canvasSceneLogicActions {
    clearStartHandoff: () => {
        value: true
    } // canvasNewLogic
    openTab: (
        tab: import('../sidePanel/canvasPanelTabs').CanvasPanelTab,
        canvasId: string
    ) => {
        canvasId: string
        tab: import('../sidePanel/canvasPanelTabs').CanvasPanelTab
    } // canvasSidePanelLogic
    setOpenCanvasBuilding: (
        canvasId: string,
        building: boolean | null
    ) => {
        building: boolean | null
        canvasId: string
    } // todayViewsLogic
    buildAction: (
        action: CanvasBuildActionActionEnumApi,
        buildId: string
    ) => {
        action: CanvasBuildActionActionEnumApi
        buildId: string
    }
    buildActionFinished: () => {
        value: true
    }
    canvasUpdated: (canvas: CanvasApi) => {
        canvas: CanvasApi
    }
    canvasVisibilityChanged: () => {
        value: true
    }
    closeMakePublic: () => {
        value: true
    }
    copyLink: () => {
        value: true
    }
    deleteCanvas: () => {
        value: true
    }
    generateCanvas: (
        instruction: string,
        fromSuggestion: boolean,
        surface?: CanvasSurface
    ) => {
        fromSuggestion: boolean
        instruction: string
        surface: CanvasSurface
    }
    generationFailed: (message: string) => {
        message: string
    }
    generationFinished: () => {
        value: true
    }
    generationStarted: () => {
        value: true
    }
    loadBuilds: () => any
    loadBuildsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadBuildsSuccess: (
        builds: CanvasBuildsResponseApi | null,
        payload?: any
    ) => {
        builds: CanvasBuildsResponseApi | null
        payload?: any
    }
    loadGenerationTask: () => any
    loadGenerationTaskFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadGenerationTaskSuccess: (
        generationTask: CanvasGenerationTask | null,
        payload?: any
    ) => {
        generationTask: CanvasGenerationTask | null
        payload?: any
    }
    loadSpace: () => any
    loadSpaceFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadSpaceSuccess: (
        space: CanvasSpace | null,
        payload?: any
    ) => {
        space: CanvasSpace | null
        payload?: any
    }
    loadView: () => any
    loadViewFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadViewSuccess: (
        view: CanvasViewResponseApi | null,
        payload?: any
    ) => {
        view: CanvasViewResponseApi | null
        payload?: any
    }
    moveCanvasToSpace: (
        spaceId: string,
        visibility: 'private' | 'public' | null,
        restricted: boolean,
        restoreTasks?: CanvasTaskMove[]
    ) => {
        restoreTasks: CanvasTaskMove[]
        restricted: boolean
        spaceId: string
        visibility: 'private' | 'public' | null
    }
    openMakePublic: () => {
        value: true
    }
    poll: () => {
        value: true
    }
    renameCanvas: (name: string) => {
        name: string
    }
    reportBusy: () => {
        value: true
    }
    requestFix: (request: CanvasFixRequest) => {
        request: CanvasFixRequest
    }
    requestFixFinished: (result: CanvasFixRequestResultApi | null) => {
        result: CanvasFixRequestResultApi | null
    }
    setAgentTurn: (
        runId: string,
        active: boolean | null
    ) => {
        active: boolean | null
        runId: string
    }
    setCanvasVisibility: (visibility: 'private' | 'public') => {
        visibility: 'private' | 'public'
    }
    setInstruction: (
        instruction: string,
        fromSuggestion: boolean
    ) => {
        fromSuggestion: boolean
        instruction: string
    }
    setRuntimeError: (message: string | null) => {
        message: string | null
    }
    startPolling: () => {
        value: true
    }
    stopPolling: () => {
        value: true
    }
    syncGenerationStream: () => {
        value: true
    }
    syncSidePanel: () => {
        value: true
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface canvasSceneLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        busy: (isGenerating: boolean, buildStatus: CanvasBuildStatus) => boolean
        canvas: (view: CanvasViewResponseApi | null) => CanvasApi | null
        visibility: (canvas: CanvasApi | null, space: CanvasSpace | null) => CanvasVisibility | null
        isCreator: (canvas: CanvasApi | null, user: UserType | null) => boolean
        sandboxDocumentUrl: (view: CanvasViewResponseApi | null) => string | null
        liveBuild: (view: CanvasViewResponseApi | null) => CanvasBuildApi | null
        draftCode: (view: CanvasViewResponseApi | null) => string | null
        liveRenderSource: (liveBuild: CanvasBuildApi | null, view: CanvasViewResponseApi | null) => CanvasRenderSource
        buildStatus: (builds: CanvasBuildsResponseApi | null, view: CanvasViewResponseApi | null) => CanvasBuildStatus
        isGenerating: (
            view: CanvasViewResponseApi | null,
            generationTask: CanvasGenerationTask | null,
            generationTaskLoading: boolean,
            agentTurn: CanvasAgentTurn | null
        ) => boolean
        bodyState: (
            view: CanvasViewResponseApi | null,
            viewLoading: boolean,
            viewMissing: boolean,
            viewUnavailable: boolean,
            liveBuild: CanvasBuildApi | null,
            draftCode: string | null,
            sandboxDocumentUrl: string | null,
            isGenerating: boolean
        ) => CanvasBodyState
        generationPhase: (
            isGenerating: boolean,
            generationTask: CanvasGenerationTask | null,
            view: CanvasViewResponseApi | null
        ) => CanvasGenerationPhase | null
        sidePanelAvailable: (bodyState: CanvasBodyState) => boolean
        sidePanelContext: (arg: string, blocksCanvasId: string | null) => SidePanelSceneContext
        shouldPoll: (
            view: CanvasViewResponseApi | null,
            isGenerating: boolean,
            buildStatus: CanvasBuildStatus
        ) => boolean
        breadcrumbs: (canvas: CanvasApi | null, space: CanvasSpace | null, arg: string) => Breadcrumb[]
    }
}

export type canvasSceneLogicType = MakeLogicType<
    canvasSceneLogicValues,
    canvasSceneLogicActions,
    CanvasSceneLogicProps,
    canvasSceneLogicMeta
>

export const canvasSceneLogic = kea<canvasSceneLogicType>([
    props({} as CanvasSceneLogicProps),
    key((props) => props.id),
    path((key) => ['products', 'canvas', 'frontend', 'scene', 'canvasSceneLogic', key]),
    connect(() => ({
        // The start page hands over a prompt whose canvas exists but whose build did not start.
        values: [
            projectLogic,
            ['currentProjectId'],
            canvasNewLogic,
            ['startHandoff'],
            sidePanelStateLogic,
            ['selectedTab', 'sidePanelOpen'],
            canvasSidePanelLogic,
            ['blocksCanvasId'],
            userLogic,
            ['user'],
        ],
        // Connecting keeps the Views sidebar's logic mounted, so it knows this canvas's state when it opens.
        actions: [
            canvasNewLogic,
            ['clearStartHandoff'],
            canvasSidePanelLogic,
            ['openTab'],
            todayViewsLogic,
            ['setOpenCanvasBuilding'],
        ],
    })),
    actions({
        renameCanvas: (name: string) => ({ name }),
        canvasUpdated: (canvas: CanvasApi) => ({ canvas }),
        copyLink: true,
        deleteCanvas: true,
        openMakePublic: true,
        closeMakePublic: true,
        setCanvasVisibility: (visibility: 'private' | 'public') => ({ visibility }),
        /**
         * Moves the canvas to a space. `visibility` is null when the move undoes the one before.
         * `restricted` says the space is not the team's, so the creator's chats on the canvas move there first.
         */
        moveCanvasToSpace: (
            spaceId: string,
            visibility: 'private' | 'public' | null,
            restricted: boolean,
            restoreTasks: CanvasTaskMove[] = []
        ) => ({
            spaceId,
            visibility,
            restricted,
            restoreTasks,
        }),
        canvasVisibilityChanged: true,
        setInstruction: (instruction: string, fromSuggestion: boolean) => ({ instruction, fromSuggestion }),
        generateCanvas: (
            instruction: string,
            fromSuggestion: boolean,
            surface: CanvasSurface = 'web_canvas_scene'
        ) => ({
            instruction,
            fromSuggestion,
            surface,
        }),
        generationStarted: true,
        /** Tells the Views sidebar whether this canvas is busy, when that changed. */
        reportBusy: true,
        generationFinished: true,
        generationFailed: (message: string) => ({ message }),
        setRuntimeError: (message: string | null) => ({ message }),
        buildAction: (action: CanvasBuildActionActionEnumApi, buildId: string) => ({ action, buildId }),
        buildActionFinished: true,
        requestFix: (request: CanvasFixRequest) => ({ request }),
        requestFixFinished: (result: CanvasFixRequestResultApi | null) => ({ result }),
        startPolling: true,
        stopPolling: true,
        poll: true,
        setAgentTurn: (runId: string, active: boolean | null) => ({ runId, active }),
        /** Follows the agent's turn on the run writing the canvas, through that run's session stream. */
        syncGenerationStream: true,
        /** Shows the canvas tabs in the app side panel where the canvas needs them. */
        syncSidePanel: true,
    }),
    loaders(({ props, values }) => ({
        view: [
            null as CanvasViewResponseApi | null,
            {
                loadView: async () =>
                    values.currentProjectId
                        ? await canvasesViewRetrieve(String(values.currentProjectId), props.id)
                        : null,
            },
        ],
        builds: [
            null as CanvasBuildsResponseApi | null,
            {
                loadBuilds: async () =>
                    values.currentProjectId
                        ? await canvasesBuildsRetrieve(String(values.currentProjectId), props.id, { scope: 'slim' })
                        : null,
            },
        ],
        generationTask: [
            null as CanvasGenerationTask | null,
            {
                loadGenerationTask: async () => {
                    const taskId = values.view?.canvas.generation_task_id
                    return values.currentProjectId && taskId
                        ? await loadCanvasGenerationTask(String(values.currentProjectId), taskId)
                        : null
                },
            },
        ],
        space: [
            null as CanvasSpace | null,
            {
                loadSpace: async () => {
                    const spaceId = values.view?.canvas.channel
                    return values.currentProjectId && spaceId
                        ? await loadCanvasSpace(String(values.currentProjectId), spaceId)
                        : null
                },
            },
        ],
    })),
    reducers({
        view: {
            canvasUpdated: (state, { canvas }) => (state ? { ...state, canvas } : state),
        },
        makePublicOpen: [
            false,
            {
                openMakePublic: () => true,
                closeMakePublic: () => false,
                canvasVisibilityChanged: () => false,
            },
        ],
        visibilityChanging: [
            false,
            {
                setCanvasVisibility: () => true,
                moveCanvasToSpace: () => true,
                canvasVisibilityChanged: () => false,
            },
        ],
        viewMissing: [
            false,
            {
                loadView: () => false,
                loadViewFailure: (_, { errorObject }) => errorObject?.status === 404,
            },
        ],
        viewUnavailable: [
            false,
            {
                loadViewSuccess: () => false,
                loadViewFailure: () => true,
            },
        ],
        instruction: [
            '',
            {
                setInstruction: (_, { instruction }) => instruction,
                generationStarted: () => '',
            },
        ],
        instructionFromSuggestion: [
            false,
            {
                setInstruction: (_, { fromSuggestion }) => fromSuggestion,
                generationStarted: () => false,
            },
        ],
        generationStarting: [
            false,
            {
                generateCanvas: () => true,
                generationFinished: () => false,
            },
        ],
        // Why the last run didn't start, kept on screen so the side panel can say so.
        generationError: [
            null as string | null,
            {
                generateCanvas: () => null,
                generationFailed: (_, { message }) => message,
                requestFix: () => null,
            },
        ],
        // The last error the rendered canvas threw. Cleared when it renders again.
        runtimeError: [
            null as string | null,
            {
                setRuntimeError: (_, { message }) => message,
                loadViewSuccess: (state, { view }) => (view ? state : null),
            },
        ],
        buildActionPending: [
            false,
            {
                buildAction: () => true,
                buildActionFinished: () => false,
            },
        ],
        fixRequestPending: [
            false,
            {
                requestFix: () => true,
                requestFixFinished: () => false,
            },
        ],
        agentTurn: [
            null as CanvasAgentTurn | null,
            {
                setAgentTurn: (_, { runId, active }) => ({ runId, active }),
            },
        ],
        // The run a fix request routed to. The chat panel follows it until the canvas record catches up.
        fixTaskId: [
            null as string | null,
            {
                requestFixFinished: (state, { result }) => result?.task_id ?? state,
            },
        ],
    }),
    selectors({
        /** Whether an agent or a build is at work on the canvas, which the Views sidebar marks with a spinner. */
        busy: [
            (s) => [s.isGenerating, s.buildStatus],
            (isGenerating: boolean, buildStatus: CanvasBuildStatus): boolean =>
                isGenerating || buildStatus === 'building',
        ],
        canvas: [(s) => [s.view], (view: CanvasViewResponseApi | null): CanvasApi | null => view?.canvas ?? null],
        /** Null until the canvas's space loads, so the header shows no visibility it might take back. */
        visibility: [
            (s) => [s.canvas, s.space],
            (canvas: CanvasApi | null, space: CanvasSpace | null): CanvasVisibility | null =>
                canvas && space?.id === canvas.channel ? canvasVisibility(space) : null,
        ],
        /** Only the canvas's creator may move it, so only they get the visibility actions. */
        isCreator: [
            (s) => [s.canvas, s.user],
            (canvas: CanvasApi | null, user: UserType | null): boolean =>
                !!canvas && !!user && canvas.created_by.id === user.id,
        ],
        sandboxDocumentUrl: [
            (s) => [s.view],
            (view: CanvasViewResponseApi | null): string | null => view?.sandbox_document_url ?? null,
        ],
        liveBuild: [
            (s) => [s.view],
            (view: CanvasViewResponseApi | null): CanvasBuildApi | null => {
                const build = view?.published_build
                return build?.build_status === 'ready' && build.artifact_url ? build : null
            },
        ],
        draftCode: [
            (s) => [s.view],
            (view: CanvasViewResponseApi | null): string | null => view?.source?.files[CANVAS_COMPONENT_PATH] ?? null,
        ],
        liveRenderSource: [
            (s) => [s.liveBuild, s.view],
            (liveBuild: CanvasBuildApi | null, view: CanvasViewResponseApi | null): CanvasRenderSource => ({
                sourceVersionId: liveBuild ? liveBuild.source_version_id : (view?.current_version_id ?? null),
                build: liveBuild,
                draftSource: view?.source ?? null,
            }),
        ],
        buildStatus: [
            (s) => [s.builds, s.view],
            (builds: CanvasBuildsResponseApi | null, view: CanvasViewResponseApi | null): CanvasBuildStatus =>
                canvasBuildStatus(builds, view),
        ],
        isGenerating: [
            // A run that is still starting is not generating yet: the composer stays up, so a
            // failed start keeps what the person typed.
            (s) => [s.view, s.generationTask, s.generationTaskLoading, s.agentTurn],
            (
                view: CanvasViewResponseApi | null,
                task: CanvasGenerationTask | null,
                taskLoading: boolean,
                agentTurn: CanvasAgentTurn | null
            ): boolean => {
                const taskId = view?.canvas.generation_task_id
                if (!taskId) {
                    return false
                }
                // Assume the run is live until its record says otherwise.
                if (!task || task.id !== taskId) {
                    return taskLoading || !task
                }
                const run = task.latest_run
                if (!run || isTerminalRunStatus(run.status)) {
                    return false
                }
                if (isStartingRunStatus(run.status) || agentTurn?.runId !== run.id || agentTurn.active === null) {
                    return true
                }
                return agentTurn.active
            },
        ],
        bodyState: [
            (s) => [
                s.view,
                s.viewLoading,
                s.viewMissing,
                s.viewUnavailable,
                s.liveBuild,
                s.draftCode,
                s.sandboxDocumentUrl,
                s.isGenerating,
            ],
            (
                view: CanvasViewResponseApi | null,
                viewLoading: boolean,
                missing: boolean,
                unavailable: boolean,
                liveBuild: CanvasBuildApi | null,
                draftCode: string | null,
                sandboxDocumentUrl: string | null,
                isGenerating: boolean
            ): CanvasBodyState => {
                if (missing) {
                    return 'missing'
                }
                if (!view) {
                    return unavailable ? 'error' : 'loading'
                }
                if (liveBuild) {
                    return 'built'
                }
                if (draftCode) {
                    return sandboxDocumentUrl ? 'draft' : 'draft-unavailable'
                }
                if (isGenerating) {
                    return 'generating'
                }
                if (view.canvas.generation_task_id || view.current_version_id) {
                    return viewLoading ? 'loading' : 'generation-ended'
                }
                return 'empty'
            },
        ],
        generationPhase: [
            (s) => [s.isGenerating, s.generationTask, s.view],
            (
                isGenerating: boolean,
                task: CanvasGenerationTask | null,
                view: CanvasViewResponseApi | null
            ): CanvasGenerationPhase | null => {
                if (!isGenerating) {
                    return null
                }
                const run = task && task.id === view?.canvas.generation_task_id ? task.latest_run : null
                return !run || isStartingRunStatus(run.status) ? 'starting' : 'running'
            },
        ],
        // The panel has nothing to add to a canvas that has not loaded, or to an empty one whose composer fills the body.
        sidePanelAvailable: [
            (s) => [s.bodyState],
            (bodyState: CanvasBodyState): boolean => !['loading', 'error', 'missing', 'empty'].includes(bodyState),
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [(_, props: CanvasSceneLogicProps) => props.id, s.blocksCanvasId],
            (canvasId: string, blocksCanvasId: string | null): SidePanelSceneContext => ({
                canvas_id: canvasId,
                canvas_blocks: blocksCanvasId === canvasId,
            }),
        ],
        shouldPoll: [
            (s) => [s.view, s.isGenerating, s.buildStatus],
            (view: CanvasViewResponseApi | null, isGenerating: boolean, buildStatus: CanvasBuildStatus): boolean =>
                !!view && (isGenerating || buildStatus === 'building'),
        ],
        breadcrumbs: [
            (s) => [s.canvas, s.space, (_, props: CanvasSceneLogicProps) => props.id],
            (canvas: CanvasApi | null, space: CanvasSpace | null, id: string): Breadcrumb[] => [
                ...(space
                    ? [{ key: 'canvas-space', name: canvasSpaceLabel(space), path: urls.taskSpace(space.id) }]
                    : []),
                { key: ['CanvasDetail', id], name: canvas?.name ?? 'Canvas' },
            ],
        ],
    }),
    listeners(({ actions, values, props, cache }) => ({
        reportBusy: () => {
            if (cache.reportedBusy !== values.busy) {
                cache.reportedBusy = values.busy
                actions.setOpenCanvasBuilding(props.id, values.busy)
            }
        },
        loadViewSuccess: ({ view }) => {
            actions.reportBusy()
            if (!view) {
                return
            }
            if (!cache.viewedTracked) {
                cache.viewedTracked = true
                posthog.capture(CANVAS_EVENTS.viewed, {
                    channel_id: view.canvas.channel,
                    dashboard_id: view.canvas.id,
                    canvas_kind: view.canvas.kind,
                    template_id: view.canvas.template_id,
                })
            }
            if (!values.space || values.space.id !== view.canvas.channel) {
                actions.loadSpace()
            }
            if (view.canvas.generation_task_id && values.generationTask?.id !== view.canvas.generation_task_id) {
                actions.loadGenerationTask()
            }
            if (values.shouldPoll) {
                actions.startPolling()
            }
            actions.syncGenerationStream()
            actions.syncSidePanel()
        },
        loadGenerationTaskSuccess: () => {
            actions.reportBusy()
            if (values.shouldPoll) {
                actions.startPolling()
            } else {
                actions.stopPolling()
            }
            actions.syncGenerationStream()
            actions.syncSidePanel()
        },
        canvasUpdated: () => {
            actions.syncGenerationStream()
            actions.reportBusy()
        },
        setAgentTurn: () => {
            actions.reportBusy()
            // A follow-up on the same run reopens the turn, so polling follows the turn both ways.
            if (values.shouldPoll) {
                actions.startPolling()
            } else {
                actions.stopPolling()
            }
        },
        syncGenerationStream: () => {
            const taskId = values.view?.canvas.generation_task_id ?? null
            const task = values.generationTask
            const run = task && task.id === taskId ? task.latest_run : null
            const runId = run && !isStartingRunStatus(run.status) && !isTerminalRunStatus(run.status) ? run.id : null
            if (runId === (cache.generationStreamRunId ?? null)) {
                return
            }
            cache.generationStreamRunId = runId
            if (!taskId || !runId) {
                cache.disposables.dispose('generationStream')
                return
            }
            cache.disposables.add(() => {
                // The chat tab's live thread uses the same stream, so the run connects once.
                const stream = runStreamLogic({ streamKey: runId })
                const unmount = stream.mount()
                if (stream.values.bootstrappedRunId !== runId) {
                    stream.actions.bootstrapRun({ taskId, runId })
                }
                let reported: boolean | null | undefined
                const report = (): void => {
                    const active = readAgentTurn(stream)
                    if (active !== reported) {
                        reported = active
                        actions.setAgentTurn(runId, active)
                    }
                }
                const unsubscribe = getContext().store.subscribe(report)
                report()
                return () => {
                    unsubscribe()
                    unmount()
                }
            }, 'generationStream')
        },
        [sidePanelStateLogic.actionTypes.openSidePanel]: ({ tab }) => {
            // The canvas tabs replace the general ones, so the context panel button and shortcut open the chat.
            if (replacedByCanvasTabs(tab)) {
                actions.openTab('chat', props.id)
            }
        },
        syncSidePanel: () => {
            // A general tab left open from another page has nothing to show here, so the panel moves to the chat.
            if (values.sidePanelOpen && values.selectedTab && replacedByCanvasTabs(values.selectedTab)) {
                actions.openTab('chat', props.id)
                return
            }
            if (values.sidePanelOpen) {
                return
            }
            // While the agent writes a canvas with nothing to show yet, its chat is the only content. It opens once per visit.
            if (values.bodyState === 'generating' && !cache.generatingPanelOpened) {
                cache.generatingPanelOpened = true
                actions.openTab('chat', props.id)
            }
        },
        loadBuildsSuccess: ({ builds }) => {
            actions.reportBusy()
            const view = values.view
            // A new live build or head version changes what renders, so the view is re-read.
            if (
                builds &&
                view &&
                (builds.published_build_id !== view.published_build?.id ||
                    builds.current_version_id !== view.current_version_id)
            ) {
                actions.loadView()
            }
            if (!values.shouldPoll) {
                actions.stopPolling()
            }
        },
        startPolling: () => {
            cache.disposables.add(() => {
                const id = setInterval(() => actions.poll(), POLL_INTERVAL_MS)
                return () => clearInterval(id)
            }, 'poll')
        },
        stopPolling: () => {
            cache.disposables.dispose('poll')
        },
        poll: () => {
            if (!values.shouldPoll) {
                actions.stopPolling()
                return
            }
            if (!values.buildsLoading) {
                actions.loadBuilds()
            }
            if (values.view?.canvas.generation_task_id && !values.generationTaskLoading) {
                actions.loadGenerationTask()
            }
        },
        renameCanvas: async ({ name }) => {
            const trimmed = name.trim()
            if (!values.currentProjectId || !values.canvas || !trimmed || trimmed === values.canvas.name) {
                return
            }
            try {
                const canvas = await canvasesPartialUpdate(String(values.currentProjectId), props.id, { name: trimmed })
                actions.canvasUpdated(canvas)
                // The Views sidebar lists canvases by name.
                todayViewsLogic.findMounted()?.actions.loadRecentViews()
            } catch (error) {
                toast.error({
                    title: "Couldn't rename the canvas",
                    description: error instanceof Error ? error.message : 'Try again in a moment.',
                })
            }
        },
        openMakePublic: () => {
            if (values.canvas) {
                captureCanvasAction('make_public_opened', {
                    dashboard_id: values.canvas.id,
                    channel_id: values.canvas.channel,
                })
            }
        },
        setCanvasVisibility: async ({ visibility }) => {
            if (!values.currentProjectId) {
                actions.canvasVisibilityChanged()
                return
            }
            try {
                const spaces = await loadCanvasSpaces(String(values.currentProjectId))
                const space = visibilitySpace(spaces, visibility)
                if (!space) {
                    throw new Error('This project has no team space yet.')
                }
                actions.moveCanvasToSpace(space.id, visibility, visibility === 'private')
            } catch (error) {
                toast.error({
                    title:
                        visibility === 'public'
                            ? "Couldn't make the canvas public"
                            : "Couldn't make the canvas private",
                    description: error instanceof Error ? error.message : 'Try again in a moment.',
                })
                actions.canvasVisibilityChanged()
            }
        },
        moveCanvasToSpace: async ({ spaceId, visibility, restricted, restoreTasks }) => {
            const canvas = values.canvas
            if (!values.currentProjectId || !canvas) {
                actions.canvasVisibilityChanged()
                return
            }
            const projectId = String(values.currentProjectId)
            const previousSpaceId = canvas.channel
            const previousRestricted = values.visibility !== 'public'
            const properties = { dashboard_id: canvas.id, ...(visibility ? { visibility } : {}), undo: !visibility }
            let moved: CanvasTaskMove[] = []
            try {
                // Chats first: a task's logs are as visible as its own space, whatever the canvas says.
                if (restricted && values.user) {
                    moved = await moveCanvasTasks(
                        projectId,
                        await ownCanvasTaskIds(projectId, canvas, values.user),
                        spaceId
                    )
                }
                let updated: CanvasApi
                try {
                    updated = await canvasesPartialUpdate(projectId, props.id, { channel_id: spaceId })
                } catch (error) {
                    // The canvas stayed, so its chats go back to stay in the same space as it.
                    const unrestored = await restoreCanvasTasks(projectId, moved)
                    throw unrestored ? new Error(partialMoveMessage(unrestored)) : error
                }
                const unrestored = await restoreCanvasTasks(projectId, restoreTasks)
                actions.canvasUpdated(updated)
                actions.loadSpace()
                todayViewsLogic.findMounted()?.actions.loadRecentViews()
                captureCanvasAction('visibility_change', { ...properties, channel_id: spaceId, success: true })
                toast.success(
                    visibility
                        ? {
                              title:
                                  visibility === 'public' ? 'This canvas is now public' : 'This canvas is now private',
                              action: {
                                  label: 'Undo',
                                  onClick: () =>
                                      actions.moveCanvasToSpace(previousSpaceId, null, previousRestricted, moved),
                              },
                          }
                        : unrestored
                          ? { title: 'Change undone. Some of its chats stayed private.' }
                          : { title: 'Change undone' }
                )
            } catch (error) {
                captureCanvasAction('visibility_change', { ...properties, channel_id: previousSpaceId, success: false })
                toast.error({
                    title:
                        visibility === 'public'
                            ? "Couldn't make the canvas public"
                            : visibility === 'private'
                              ? "Couldn't make the canvas private"
                              : "Couldn't undo the change",
                    description: error instanceof Error ? error.message : 'Try again in a moment.',
                })
            } finally {
                actions.canvasVisibilityChanged()
            }
        },
        copyLink: async () => {
            // The project in the path makes the link open this canvas for someone whose current project differs.
            await copyToClipboard(urls.absolute(urls.currentProject(urls.canvasDetail(props.id))), 'canvas link')
        },
        deleteCanvas: () => {
            const canvas = values.canvas
            if (!values.currentProjectId || !canvas) {
                return
            }
            deleteCanvasWithUndo({
                projectId: String(values.currentProjectId),
                canvasId: canvas.id,
                spaceId: canvas.channel,
                name: canvas.name,
                surface: 'web_canvas_scene',
                onRestore: () => router.actions.push(urls.canvasDetail(canvas.id)),
            })
            router.actions.push(urls.taskSpace(canvas.channel))
        },
        generateCanvas: async ({ instruction, fromSuggestion, surface }) => {
            const canvas = values.canvas
            if (!values.currentProjectId || !canvas || !instruction.trim()) {
                actions.generationFinished()
                return
            }
            try {
                const started = await startCanvasGeneration({
                    projectId: String(values.currentProjectId),
                    canvas,
                    spaceName: values.space?.name ?? null,
                    instruction,
                    fromSuggestion,
                    surface,
                })
                actions.canvasUpdated(started.canvas)
                actions.loadGenerationTaskSuccess(started.task)
                actions.generationStarted()
                actions.startPolling()
                actions.openTab('chat', canvas.id)
            } catch (error) {
                const message = error instanceof Error ? error.message : 'Try again in a moment.'
                actions.generationFailed(message)
                toast.error({ title: "Couldn't start building the canvas", description: message })
            } finally {
                actions.generationFinished()
            }
        },
        buildAction: async ({ action, buildId }) => {
            const canvas = values.canvas
            if (!values.currentProjectId || !canvas) {
                actions.buildActionFinished()
                return
            }
            let success = false
            try {
                await canvasesBuildActionCreate(String(values.currentProjectId), canvas.id, {
                    action,
                    build_id: buildId,
                })
                success = true
                actions.loadBuilds()
                if (action === 'retry') {
                    actions.startPolling()
                }
            } catch (error) {
                toast.error({
                    title: "Couldn't update the build",
                    description: error instanceof Error ? error.message : 'Try again in a moment.',
                })
            } finally {
                captureCanvasAction(`build_${action}`, { dashboard_id: canvas.id, channel_id: canvas.channel, success })
                actions.buildActionFinished()
            }
        },
        requestFix: async ({ request }) => {
            const canvas = values.canvas
            if (!values.currentProjectId || !canvas) {
                actions.requestFixFinished(null)
                return
            }
            const origin = request.errorType ? 'runtime' : 'build'
            try {
                const result = await canvasesRequestFixCreate(String(values.currentProjectId), canvas.id, {
                    build_id: request.buildId,
                    ...(request.errorType ? { error_type: request.errorType } : {}),
                })
                captureCanvasAction('fix_request', {
                    dashboard_id: canvas.id,
                    channel_id: canvas.channel,
                    origin,
                    outcome: result.dispatch_outcome,
                    success: true,
                })
                toast.success({
                    title:
                        result.dispatch_outcome === 'signaled'
                            ? 'Sent the fix request to the running agent.'
                            : result.dispatch_outcome === 'already_queued'
                              ? 'A fix run is already starting.'
                              : 'The agent is working on a fix. It stages the fix as a draft for you to review.',
                })
                actions.requestFixFinished(result)
                actions.openTab('chat', canvas.id)
                actions.loadView()
            } catch (error) {
                captureCanvasAction('fix_request', {
                    dashboard_id: canvas.id,
                    channel_id: canvas.channel,
                    origin,
                    success: false,
                })
                const message = error instanceof Error ? error.message : 'Try again in a moment.'
                toast.error({ title: "Couldn't ask the agent to fix this", description: message })
                actions.requestFixFinished(null)
            }
        },
    })),
    afterMount(({ actions, values, props }) => {
        const handoff = values.startHandoff
        if (handoff?.canvasId === props.id) {
            actions.setInstruction(handoff.instruction, handoff.fromSuggestion)
            actions.clearStartHandoff()
        }
        actions.loadView()
        actions.loadBuilds()
        actions.syncSidePanel()
    }),
    beforeUnmount(({ actions, props }) => {
        actions.setOpenCanvasBuilding(props.id, null)
    }),
])
