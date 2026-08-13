import { useActions, useMountedLogic, useValues } from 'kea'
import type { ReactNode } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { urls } from 'scenes/urls'

import { NotebookNodeProps, NotebookNodeType } from '../../types'
import { notebookNodeLogic } from '../notebookNodeLogic'
import { GenUIArtifactFrame } from './GenUIArtifactFrame'
import { buildGenUIFrames, getGenUIFrameSchemas } from './genUIFrames'
import { getGenUIGenerationProgressView } from './genUIGenerationProgress'
import { getGenUIName } from './genUIGenerationPrompt'
import { notebookNodeGenUILogic } from './notebookNodeGenUILogic'
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

function Component({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodeGenUIAttributes>): JSX.Element | null {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { expanded, isEditable, notebookLogic } = useValues(nodeLogic)
    const { content } = useValues(notebookLogic)
    const inputs = attributes.inputs ?? ''
    const frames = buildGenUIFrames(content, inputs)
    const { schemas, missing } = getGenUIFrameSchemas(content, inputs)
    const logic = notebookNodeGenUILogic({
        id: attributes.id ?? '',
        nodeId: attributes.nodeId,
        channelId: attributes.channelId,
        prompt: attributes.prompt ?? '',
        frames: schemas,
        missingFrames: missing,
        isEditable,
        updateAttributes,
    })
    const {
        artifactUrl,
        buildsLoading,
        canvas,
        canvasCreationError,
        canvasLoading,
        canvasMissing,
        capabilities,
        creatingCanvas,
        generationError,
        generationProgress,
        generationWatch,
        isGenerating,
        runtimeError,
    } = useValues(logic)
    const { createFromPrompt, setRuntimeError } = useActions(logic)
    const generationProgressView = generationWatch
        ? getGenUIGenerationProgressView(generationProgress, generationWatch.observedAtMs, Date.now())
        : null

    const generationStatus = generationProgressView ? (
        <div className="flex min-w-0 flex-1 items-center gap-2" role="status" aria-live="polite">
            <Spinner className="shrink-0 text-sm" />
            <div className="min-w-0 flex-1">
                <div className="font-semibold text-primary">{generationProgressView.label}</div>
                <div className="text-muted">{generationProgressView.detail}</div>
            </div>
            {generationWatch ? (
                <LemonButton size="xsmall" to={urls.taskDetail(generationWatch.taskId)}>
                    View task
                </LemonButton>
            ) : null}
        </div>
    ) : null

    if (!expanded) {
        return null
    }
    if ((canvasLoading || buildsLoading) && !artifactUrl) {
        return (
            <div className="flex h-full flex-col gap-3 p-3">
                <LemonSkeleton className="h-6 w-1/3" />
                <LemonSkeleton className="min-h-32 flex-1 w-full" />
            </div>
        )
    }
    if (canvasMissing) {
        return <NotFound object="visualization" />
    }
    if (artifactUrl) {
        return (
            <div className="flex h-full min-h-0 w-full flex-col">
                {isGenerating ? (
                    <div className="flex shrink-0 border-b border-primary px-3 py-2 text-xs">{generationStatus}</div>
                ) : null}
                {generationError ? (
                    <LemonBanner type="error" className="m-2">
                        {generationError}
                    </LemonBanner>
                ) : null}
                {runtimeError ? (
                    <LemonBanner type="warning" className="m-2" onClose={() => setRuntimeError(null)}>
                        The visualization reported an error: {runtimeError}
                    </LemonBanner>
                ) : null}
                <div className="min-h-0 flex-1">
                    <GenUIArtifactFrame
                        artifactUrl={artifactUrl}
                        capabilities={capabilities}
                        frames={frames}
                        onError={setRuntimeError}
                        onRendered={() => setRuntimeError(null)}
                    />
                </div>
            </div>
        )
    }

    const error = canvasCreationError || generationError
    if (error) {
        return (
            <EmptyState>
                <div className="flex flex-col items-center gap-3">
                    <div>{error}</div>
                    {isEditable ? (
                        <LemonButton type="primary" onClick={() => createFromPrompt()} loading={creatingCanvas}>
                            Try again
                        </LemonButton>
                    ) : null}
                    {canvas?.generation_task_id ? (
                        <LemonButton to={urls.taskDetail(canvas.generation_task_id)}>View generation task</LemonButton>
                    ) : null}
                </div>
            </EmptyState>
        )
    }
    if (creatingCanvas || isGenerating) {
        return (
            <EmptyState>
                <div className="flex w-full max-w-lg flex-col items-center gap-3">
                    {generationStatus ?? (
                        <div className="flex items-center gap-2" role="status">
                            <Spinner /> Starting visualization generation
                        </div>
                    )}
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
                    <LemonButton type="primary" onClick={() => createFromPrompt()} loading={creatingCanvas}>
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
