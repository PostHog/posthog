import { useActions, useMountedLogic, useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { NotebookNodeProps, NotebookNodeType } from '../../types'
import { notebookNodeLogic } from '../notebookNodeLogic'
import { GenUIArtifactFrame } from './GenUIArtifactFrame'
import { DEFAULT_GENUI_MODEL, GenUIModel } from './genUIModels'
import { getGenUIName } from './genUIName'
import { formatGenUIElapsed, loadGenUIFrame, notebookNodeGenUILogic } from './notebookNodeGenUILogic'
import { NotebookNodeGenUISettings } from './NotebookNodeGenUISettings'

export type NotebookNodeGenUIAttributes = {
    prompt?: string
    model?: GenUIModel
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
    const logic = notebookNodeGenUILogic({
        notebookShortId,
        nodeId: attributes.nodeId,
        prompt: attributes.prompt ?? '',
        model: attributes.model ?? DEFAULT_GENUI_MODEL,
        isEditable,
        persistNotebook: async (): Promise<void> => {
            await notebookLogic.asyncActions.saveNotebook({
                content: notebookLogic.values.content,
                title: notebookLogic.values.title,
            })
        },
    })
    const {
        cancellationInFlight,
        currentTeamId,
        elapsedSeconds,
        error,
        frameRevision,
        generationInFlight,
        isWorking,
        runtimeError,
        selectedVersion,
        selectedVersionId,
        status,
        statusLoading,
        workingStatus,
    } = useValues(logic)
    const { cancelGeneration, generateVisualization, loadStatus, openGenerationModal, setRuntimeError } =
        useActions(logic)

    if (!expanded) {
        return null
    }
    if (statusLoading && !status) {
        return (
            <div className="flex h-full flex-col gap-3 p-3">
                <LemonSkeleton className="h-6 w-1/3" />
                <LemonSkeleton className="min-h-32 flex-1 w-full" />
            </div>
        )
    }

    const canGenerate = Boolean((attributes.prompt ?? '').trim())
    const selectedArtifactUrl =
        selectedVersion?.artifact_url ??
        (selectedVersionId === status?.current_version_id ? status?.artifact_url : null)

    if (selectedArtifactUrl && currentTeamId) {
        return (
            <div className="flex h-full min-h-0 w-full flex-col">
                {error ? (
                    <LemonBanner type="error" className="m-2">
                        {error}
                    </LemonBanner>
                ) : null}
                {status?.lifecycle_status === 'failed' && status.error_detail ? (
                    <LemonBanner type="error" className="m-2">
                        {status.error_detail}
                    </LemonBanner>
                ) : null}
                {runtimeError ? (
                    <LemonBanner type="warning" className="m-2" onClose={() => setRuntimeError(null)}>
                        {runtimeError}
                    </LemonBanner>
                ) : null}
                <div className="min-h-0 flex-1">
                    <GenUIArtifactFrame
                        key={`${selectedArtifactUrl}-${frameRevision}`}
                        artifactUrl={selectedArtifactUrl}
                        allowedFrames={status?.frame_names ?? []}
                        onReadFrame={(name) =>
                            loadGenUIFrame(String(currentTeamId), notebookShortId, attributes.nodeId, name)
                        }
                        onArtifactUnavailable={loadStatus}
                        onError={() =>
                            setRuntimeError(
                                'The visualization hit a runtime error. Regenerate it if the problem continues.'
                            )
                        }
                        onRendered={() => setRuntimeError(null)}
                    />
                </div>
            </div>
        )
    }

    if (isWorking) {
        return (
            <EmptyState>
                <div className="flex flex-col items-center gap-3">
                    <div className="flex items-center gap-2" role="status" aria-live="polite">
                        <Spinner />
                        <span>{workingStatus?.label}</span>
                        <span className="font-mono tabular-nums">Elapsed {formatGenUIElapsed(elapsedSeconds)}</span>
                    </div>
                    {workingStatus ? (
                        <div className="flex max-w-lg flex-col gap-1 text-sm">
                            <span>{workingStatus.detail}</span>
                            <span className={workingStatus.isOverEstimate ? 'text-warning' : 'text-muted'}>
                                {workingStatus.timing}
                            </span>
                        </div>
                    ) : null}
                    {(status?.generation_id || generationInFlight) && isEditable ? (
                        <LemonButton onClick={cancelGeneration} loading={cancellationInFlight}>
                            Cancel
                        </LemonButton>
                    ) : null}
                </div>
            </EmptyState>
        )
    }

    if (status?.lifecycle_status === 'failed' || error) {
        return (
            <EmptyState>
                <div className="flex flex-col items-center gap-3">
                    <div>{status?.error_detail || error || 'The visualization could not be generated.'}</div>
                    {isEditable ? (
                        <LemonButton
                            type="primary"
                            onClick={() =>
                                status?.versions.length
                                    ? openGenerationModal('regenerate')
                                    : generateVisualization(
                                          attributes.prompt ?? '',
                                          attributes.model ?? DEFAULT_GENUI_MODEL,
                                          'initial'
                                      )
                            }
                            loading={generationInFlight}
                            disabledReason={!status?.versions.length && !canGenerate ? 'Add a prompt first' : undefined}
                        >
                            Try again
                        </LemonButton>
                    ) : null}
                </div>
            </EmptyState>
        )
    }

    if (selectedVersion) {
        return (
            <EmptyState>
                This version's preview is no longer available. You can still view its prompt and source in the block
                settings.
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
                    <LemonButton
                        type="primary"
                        onClick={() =>
                            generateVisualization(
                                attributes.prompt ?? '',
                                attributes.model ?? DEFAULT_GENUI_MODEL,
                                'initial'
                            )
                        }
                        loading={generationInFlight}
                    >
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
    serializedText: (attributes) => getGenUIName(attributes.prompt ?? ''),
    heightEstimate: 420,
    minHeight: 180,
    resizeable: true,
    fullscreenable: true,
    expandable: false,
    attributes: {
        prompt: { default: '' },
        model: { default: DEFAULT_GENUI_MODEL },
    },
})
