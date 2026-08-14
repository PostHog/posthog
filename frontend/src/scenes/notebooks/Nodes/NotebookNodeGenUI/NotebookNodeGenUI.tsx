import { useActions, useMountedLogic, useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { notebookNodeStalenessLogic } from 'scenes/notebooks/Notebook/notebookNodeStalenessLogic'
import { urls } from 'scenes/urls'

import { NotebookNodeProps, NotebookNodeType } from '../../types'
import { notebookNodeLogic } from '../notebookNodeLogic'
import { GenUICapabilities } from './genUIArtifactBridge'
import { GenUIArtifactFrame } from './GenUIArtifactFrame'
import { GenUIGenerationActivity } from './GenUIGenerationActivity'
import { validateGenUIInputs } from './genUIInputs'
import { getGenUIName } from './genUIName'
import { loadGenUIFrame, notebookNodeGenUILogic } from './notebookNodeGenUILogic'
import { NotebookNodeGenUISettings } from './NotebookNodeGenUISettings'

export type NotebookNodeGenUIAttributes = {
    id?: string
    channelId?: string
    prompt?: string
    inputs?: string
}

function EmptyState({ children }: { children: ReactNode }): JSX.Element {
    return (
        <div className="flex h-full min-h-32 items-center justify-center p-4 text-center text-secondary">
            {children}
        </div>
    )
}

function Component({ attributes }: NotebookNodeProps<NotebookNodeGenUIAttributes>): JSX.Element | null {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { expanded, isEditable, notebookLogic } = useValues(nodeLogic)
    const notebookShortId = notebookLogic.props.shortId
    const inputValidation = validateGenUIInputs(attributes.inputs ?? '')
    const logic = notebookNodeGenUILogic({
        notebookShortId,
        nodeId: attributes.nodeId,
        legacyCanvasId: attributes.id,
        prompt: attributes.prompt ?? '',
        inputs: inputValidation.names,
        inputValidationError: inputValidation.error,
        isEditable,
        getContent: () => notebookLogic.values.content,
    })
    const stalenessLogic = useMountedLogic(notebookNodeStalenessLogic({ shortId: notebookShortId }))
    const { staleNodeIds } = useValues(stalenessLogic)
    const {
        currentTeamId,
        error,
        isGenerating,
        isRefreshingInputs,
        mutationInFlight,
        runtimeError,
        status,
        statusLoading,
    } = useValues(logic)
    const {
        ensureVisualization,
        loadStatus,
        regenerateVisualization,
        reportRenderFailure,
        reportRenderSuccess,
        retryVisualization,
        runVisualization,
        setRuntimeError,
    } = useActions(logic)

    if (!expanded) {
        return null
    }
    const isWorking = mutationInFlight || isRefreshingInputs

    if ((statusLoading || isWorking) && !status) {
        return (
            <div className="flex h-full flex-col gap-3 p-3">
                <LemonSkeleton className="h-6 w-1/3" />
                <LemonSkeleton className="min-h-32 flex-1 w-full" />
            </div>
        )
    }

    const lifecycleStatus =
        staleNodeIds[attributes.nodeId] && status?.lifecycle_status === 'ready' ? 'stale' : status?.lifecycle_status
    const capabilities: GenUICapabilities | undefined = status
        ? { notebook: { frames: status.frame_names } }
        : undefined
    const generationStatus =
        isRefreshingInputs || isGenerating ? (
            <div className="flex w-full min-w-0 flex-1 items-start gap-2" role="status" aria-live="polite">
                <Spinner className="mt-0.5 shrink-0 text-sm" />
                <div className="min-w-0 flex-1">
                    <div className="font-semibold text-primary">
                        {isRefreshingInputs
                            ? 'Running required dataframe cells'
                            : lifecycleStatus === 'building'
                              ? 'Building visualization'
                              : 'Agent is building the visualization'}
                    </div>
                    <div className="text-muted">
                        {error ||
                            (isRefreshingInputs
                                ? 'The visualization will continue automatically when the cells finish.'
                                : 'This can take a few minutes.')}
                    </div>
                    {!isRefreshingInputs && status?.task_id ? (
                        <GenUIGenerationActivity taskId={status.task_id} />
                    ) : null}
                </div>
                {!isRefreshingInputs && status?.task_id ? (
                    <LemonButton size="xsmall" to={urls.taskDetail(status.task_id)}>
                        View task
                    </LemonButton>
                ) : null}
            </div>
        ) : null
    const staleBanner =
        lifecycleStatus === 'stale' ? (
            <LemonBanner type="warning" className="m-2">
                <div className="flex items-center justify-between gap-2">
                    <span>
                        Upstream dataframe results changed. Run the visualization to use the latest saved previews.
                    </span>
                    {isEditable ? (
                        <LemonButton size="small" onClick={() => runVisualization()} loading={isWorking}>
                            Run visualization
                        </LemonButton>
                    ) : null}
                </div>
            </LemonBanner>
        ) : null
    const incompatibleBanner =
        lifecycleStatus === 'incompatible' ? (
            <LemonBanner type="warning" className="m-2">
                <div className="flex items-center justify-between gap-2">
                    <span>The prompt or dataframe schema changed. Regenerate to update the visualization code.</span>
                    {isEditable ? (
                        <LemonButton size="small" onClick={() => regenerateVisualization()} loading={isWorking}>
                            Regenerate visualization
                        </LemonButton>
                    ) : null}
                </div>
            </LemonBanner>
        ) : null
    const failureBanner =
        lifecycleStatus === 'failed' ? (
            <LemonBanner type="error" className="m-2">
                <div className="flex items-center justify-between gap-2">
                    <span>{status?.error_detail || error || "Couldn't generate this visualization. Try again."}</span>
                    {isEditable ? (
                        <LemonButton size="small" onClick={() => retryVisualization()} loading={isWorking}>
                            Try again
                        </LemonButton>
                    ) : null}
                </div>
            </LemonBanner>
        ) : null

    if (status?.artifact_url && currentTeamId) {
        return (
            <div className="flex h-full min-h-0 w-full flex-col">
                {generationStatus ? (
                    <div className="flex shrink-0 border-b border-primary px-3 py-2 text-xs">{generationStatus}</div>
                ) : null}
                {staleBanner}
                {incompatibleBanner}
                {failureBanner}
                {error && lifecycleStatus !== 'failed' ? (
                    <LemonBanner type="error" className="m-2">
                        {error}
                    </LemonBanner>
                ) : null}
                {runtimeError ? (
                    <LemonBanner type="warning" className="m-2" onClose={() => setRuntimeError(null)}>
                        The visualization reported an error: {runtimeError}
                    </LemonBanner>
                ) : null}
                <div className="min-h-0 flex-1">
                    <GenUIArtifactFrame
                        artifactUrl={status.artifact_url}
                        capabilities={capabilities}
                        onReadFrame={(name) =>
                            loadGenUIFrame(String(currentTeamId), notebookShortId, attributes.nodeId, name)
                        }
                        onArtifactUnavailable={() => {
                            reportRenderFailure('artifact_unavailable')
                            setRuntimeError('The visualization link expired. Refreshing it now.')
                            loadStatus()
                        }}
                        onError={(message) => {
                            reportRenderFailure('runtime_error')
                            setRuntimeError(message)
                        }}
                        onRendered={() => {
                            reportRenderSuccess()
                            setRuntimeError(null)
                        }}
                    />
                </div>
            </div>
        )
    }

    if ((!generationStatus && error) || lifecycleStatus === 'failed') {
        const retryAction =
            lifecycleStatus === 'failed'
                ? retryVisualization
                : lifecycleStatus === 'incompatible'
                  ? regenerateVisualization
                  : lifecycleStatus === 'stale'
                    ? runVisualization
                    : ensureVisualization
        return (
            <EmptyState>
                <div className="flex flex-col items-center gap-3">
                    <div>{status?.error_detail || error}</div>
                    {isEditable ? (
                        <LemonButton type="primary" onClick={() => retryAction()} loading={isWorking}>
                            Try again
                        </LemonButton>
                    ) : null}
                    {status?.task_id ? <LemonButton to={urls.taskDetail(status.task_id)}>View task</LemonButton> : null}
                </div>
            </EmptyState>
        )
    }
    if (generationStatus) {
        return (
            <EmptyState>
                <div className="flex w-full max-w-lg flex-col items-center gap-3">{generationStatus}</div>
            </EmptyState>
        )
    }
    if (lifecycleStatus === 'awaiting_inputs') {
        const unreadyInputs = status?.input_states.filter((input) => input.input_status !== 'ready') ?? []
        return (
            <EmptyState>
                <div className="flex flex-col items-center gap-2">
                    <div>The required dataframe cells must finish before this visualization can be generated.</div>
                    {unreadyInputs.length ? (
                        <div className="text-xs text-muted">
                            {unreadyInputs
                                .map((input) => `${input.name}: ${input.input_status.replace('_', ' ')}`)
                                .join(', ')}
                        </div>
                    ) : null}
                </div>
            </EmptyState>
        )
    }
    if (!(attributes.prompt ?? '').trim()) {
        return <EmptyState>Add a prompt in the block settings.</EmptyState>
    }
    return (
        <EmptyState>
            <div className="flex flex-col items-center gap-3">
                <div>This visualization has not been generated yet.</div>
                {isEditable ? (
                    <LemonButton type="primary" onClick={() => ensureVisualization()} loading={isWorking}>
                        Generate visualization
                    </LemonButton>
                ) : null}
            </div>
        </EmptyState>
    )
}

export const NotebookNodeGenUI = createPostHogWidgetNode<NotebookNodeGenUIAttributes>({
    nodeType: NotebookNodeType.GenUI,
    titlePlaceholder: 'Custom visualization',
    Component,
    Settings: NotebookNodeGenUISettings,
    hideIdFromSettings: true,
    serializedText: (attributes) => getGenUIName(attributes.prompt ?? ''),
    heightEstimate: 420,
    minHeight: 180,
    resizeable: true,
    expandable: false,
    attributes: {
        id: { default: '' },
        channelId: {},
        prompt: { default: '' },
        inputs: { default: '' },
    },
})
