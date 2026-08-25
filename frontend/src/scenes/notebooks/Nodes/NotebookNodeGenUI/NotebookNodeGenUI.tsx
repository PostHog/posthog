import { useActions, useMountedLogic, useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { NotebookNodeProps, NotebookNodeType } from '../../types'
import { notebookNodeLogic } from '../notebookNodeLogic'
import { confirmGenUIGeneration } from './confirmGenUIGeneration'
import { GenUIArtifactFrame } from './GenUIArtifactFrame'
import { validateGenUIInputs } from './genUIInputs'
import { getGenUIName } from './genUIName'
import { loadGenUIFrame, notebookNodeGenUILogic } from './notebookNodeGenUILogic'
import { NotebookNodeGenUISettings } from './NotebookNodeGenUISettings'

export type NotebookNodeGenUIAttributes = {
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
        prompt: attributes.prompt ?? '',
        inputs: inputValidation.names,
        inputValidationError: inputValidation.error,
        isEditable,
    })
    const { currentTeamId, error, frameRevision, generationInFlight, runtimeError, status, statusLoading } =
        useValues(logic)
    const { generateVisualization, loadStatus, refreshData, setRuntimeError } = useActions(logic)

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

    const isBuilding = status?.lifecycle_status === 'building'
    const isWorking = generationInFlight || isBuilding
    const canGenerate = Boolean((attributes.prompt ?? '').trim()) && !inputValidation.error

    if (status?.artifact_url && currentTeamId) {
        return (
            <div className="flex h-full min-h-0 w-full flex-col">
                <div className="flex shrink-0 items-center justify-between gap-2 border-b border-primary px-2 py-1">
                    <span className="truncate text-xs text-muted">
                        {generationInFlight ? 'Generating updated visualization…' : 'Generated visualization'}
                    </span>
                    {isEditable ? (
                        <div className="flex shrink-0 items-center gap-1">
                            <LemonButton size="xsmall" type="tertiary" onClick={refreshData} disabled={isWorking}>
                                Reload data
                            </LemonButton>
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                onClick={() => confirmGenUIGeneration(generateVisualization)}
                                loading={generationInFlight}
                                disabledReason={
                                    !canGenerate ? inputValidation.error || 'Add a prompt first' : undefined
                                }
                            >
                                Regenerate
                            </LemonButton>
                        </div>
                    ) : null}
                </div>
                {error ? (
                    <LemonBanner type="error" className="m-2">
                        {error}
                    </LemonBanner>
                ) : null}
                {runtimeError ? (
                    <LemonBanner type="warning" className="m-2" onClose={() => setRuntimeError(null)}>
                        {runtimeError}
                    </LemonBanner>
                ) : null}
                <div className="min-h-0 flex-1">
                    <GenUIArtifactFrame
                        key={`${status.artifact_url}-${frameRevision}`}
                        artifactUrl={status.artifact_url}
                        allowedFrames={status.frame_names}
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

    if (generationInFlight || isBuilding) {
        return (
            <EmptyState>
                <div className="flex items-center gap-2" role="status" aria-live="polite">
                    <Spinner />
                    <span>{generationInFlight ? 'Generating visualization…' : 'Building visualization…'}</span>
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
                            onClick={() => confirmGenUIGeneration(generateVisualization)}
                            loading={generationInFlight}
                            disabledReason={!canGenerate ? inputValidation.error || 'Add a prompt first' : undefined}
                        >
                            Try again
                        </LemonButton>
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
                    <LemonButton
                        type="primary"
                        onClick={generateVisualization}
                        loading={generationInFlight}
                        disabledReason={inputValidation.error || undefined}
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
    expandable: false,
    attributes: {
        prompt: { default: '' },
        inputs: { default: '' },
    },
})
