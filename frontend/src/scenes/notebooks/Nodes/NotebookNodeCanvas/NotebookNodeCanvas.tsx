import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, LemonCollapse, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { wasNotebookNodeJustInserted } from 'lib/components/MarkdownNotebook/freshlyInserted'
import { NotFound } from 'lib/components/NotFound'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'
import { urls } from 'scenes/urls'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../../types'
import { notebookNodeLogic } from '../notebookNodeLogic'
import { CanvasArtifactFrame } from './CanvasArtifactFrame'
import { getCanvasNameFromPrompt, notebookNodeCanvasLogic } from './notebookNodeCanvasLogic'

const EmptyStateMessage = ({ children }: { children: React.ReactNode }): JSX.Element => (
    <div className="flex-1 flex items-center justify-center p-4 text-center text-secondary">{children}</div>
)

const Component = ({ attributes, updateAttributes }: NotebookNodeProps<NotebookNodeCanvasAttributes>): JSX.Element => {
    const { id, prompt = '' } = attributes
    const { isEditable } = useValues(notebookNodeLogic)
    const logic = notebookNodeCanvasLogic({
        id: id ?? '',
        nodeId: attributes.nodeId,
        channelId: attributes.channelId,
        prompt,
        isEditable,
        updateAttributes,
    })
    const {
        canvas,
        canvasLoading,
        canvasMissing,
        builds,
        buildsLoading,
        artifactUrl,
        capabilities,
        runtimeError,
        generationError,
        creatingCanvas,
        canvasCreationError,
        dataAccessApproved,
    } = useValues(logic)
    const { approveDataAccess, createFromPrompt, setRuntimeError } = useActions(logic)
    const { setActions, setTitlePlaceholder } = useActions(notebookNodeLogic)
    const canvasTitle = canvas?.name || getCanvasNameFromPrompt(prompt) || 'Canvas'

    useEffect(() => {
        setTitlePlaceholder(canvasTitle)
        // oxlint-disable-next-line exhaustive-deps
    }, [canvasTitle])

    useEffect(() => {
        const generationTaskId = canvas?.generation_task_id
        setActions([
            generationTaskId
                ? {
                      text: 'View generation task',
                      onClick: () => router.actions.push(urls.taskDetail(generationTaskId)),
                  }
                : undefined,
            canvas
                ? {
                      text: 'Open in PostHog Desktop',
                      onClick: () => window.open(urls.codeCanvasLink(canvas.channel, canvas.id), '_blank'),
                  }
                : undefined,
        ])
        // oxlint-disable-next-line exhaustive-deps
    }, [canvas])

    if (creatingCanvas) {
        return <EmptyStateMessage>{id ? 'Updating this canvas.' : 'Creating this canvas.'}</EmptyStateMessage>
    }

    if (canvasCreationError) {
        return (
            <EmptyStateMessage>
                <div className="deprecated-space-y-2">
                    <div>
                        Couldn't {id ? 'update' : 'create'} the canvas: {canvasCreationError}
                    </div>
                    {isEditable ? (
                        <LemonButton type="primary" onClick={() => createFromPrompt()} loading={creatingCanvas}>
                            Try again
                        </LemonButton>
                    ) : null}
                </div>
            </EmptyStateMessage>
        )
    }

    if (!id) {
        if (!prompt.trim()) {
            return <EmptyStateMessage>Add a prompt in the block settings.</EmptyStateMessage>
        }
        return (
            <EmptyStateMessage>
                <div className="deprecated-space-y-2">
                    <div>This canvas has not been created yet.</div>
                    {isEditable ? (
                        <LemonButton type="primary" onClick={() => createFromPrompt()} loading={creatingCanvas}>
                            Create canvas
                        </LemonButton>
                    ) : null}
                </div>
            </EmptyStateMessage>
        )
    }

    if (canvasMissing) {
        return <NotFound object="canvas" />
    }

    if (canvasLoading || buildsLoading) {
        return (
            <div className="p-3 deprecated-space-y-2">
                <LemonSkeleton className="h-6 w-1/3" />
                <LemonSkeleton className="h-32 w-full" />
            </div>
        )
    }

    if (!artifactUrl) {
        const generationTaskId = canvas?.generation_task_id
        if (generationError) {
            return (
                <EmptyStateMessage>
                    <div className="deprecated-space-y-2">
                        <div>{generationError}</div>
                        <div className="flex justify-center gap-2">
                            {isEditable ? (
                                <LemonButton type="primary" onClick={() => createFromPrompt()} loading={creatingCanvas}>
                                    Try again
                                </LemonButton>
                            ) : null}
                            {generationTaskId ? (
                                <LemonButton onClick={() => router.actions.push(urls.taskDetail(generationTaskId))}>
                                    View generation task
                                </LemonButton>
                            ) : null}
                        </div>
                    </div>
                </EmptyStateMessage>
            )
        }
        const buildInProgress = builds?.builds.some(
            (build) => build.build_status === 'queued' || build.build_status === 'building'
        )
        return (
            <EmptyStateMessage>
                {generationTaskId
                    ? 'This canvas has no published build yet. Open the generation task to check its progress.'
                    : buildInProgress
                      ? 'This canvas is still building. Check back in a moment.'
                      : 'This canvas has no published build yet. Publish it from PostHog Desktop to see it here.'}
            </EmptyStateMessage>
        )
    }

    if (!dataAccessApproved) {
        return (
            <EmptyStateMessage>
                <div className="deprecated-space-y-2">
                    <div>Run this canvas to let it query project data and capture events with your access.</div>
                    <LemonButton type="primary" onClick={approveDataAccess}>
                        Run canvas
                    </LemonButton>
                </div>
            </EmptyStateMessage>
        )
    }

    return (
        <div className="flex flex-col w-full h-full">
            {runtimeError ? (
                <LemonBanner type="warning" className="m-2" onClose={() => setRuntimeError(null)}>
                    The canvas reported an error: {runtimeError}
                </LemonBanner>
            ) : null}
            <CanvasArtifactFrame
                artifactUrl={artifactUrl}
                capabilities={capabilities}
                onError={setRuntimeError}
                onRendered={() => setRuntimeError(null)}
            />
        </div>
    )
}

type NotebookNodeCanvasAttributes = {
    id?: string
    channelId?: string
    prompt?: string
}

const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeCanvasAttributes>): JSX.Element => {
    const { id, prompt = '' } = attributes
    const { isEditable } = useValues(notebookNodeLogic)
    const logic = notebookNodeCanvasLogic({
        id: id ?? '',
        nodeId: attributes.nodeId,
        channelId: attributes.channelId,
        prompt,
        isEditable,
        updateAttributes,
    })
    const {
        sourceLoading,
        sourceCode,
        hasSourceChanges,
        publishResultLoading,
        isBuilding,
        publishDiagnostics,
        creatingCanvas,
    } = useValues(logic)
    const { discardSourceChanges, loadSource, setEditedCode, publishSource, createFromPrompt } = useActions(logic)

    const publishInFlight = publishResultLoading || isBuilding

    return (
        <div className="p-3 deprecated-space-y-2">
            <div className="flex-1">
                <LemonLabel>Prompt</LemonLabel>
                <LemonTextArea
                    value={prompt}
                    onChange={(value) => updateAttributes({ prompt: value || undefined })}
                    placeholder="Describe what you want this canvas to show."
                    minRows={6}
                    autoFocus={wasNotebookNodeJustInserted(attributes.nodeId)}
                />
            </div>
            <LemonButton
                type="primary"
                onClick={() => createFromPrompt()}
                loading={creatingCanvas}
                disabledReason={
                    creatingCanvas
                        ? id
                            ? 'Updating the canvas'
                            : 'Creating the canvas'
                        : !prompt.trim()
                          ? 'Add a prompt first'
                          : undefined
                }
            >
                {id ? 'Update canvas' : 'Create canvas'}
            </LemonButton>
            {id ? (
                <LemonCollapse
                    size="small"
                    onChange={(activeKey) => {
                        if (activeKey === 'source') {
                            loadSource()
                        }
                    }}
                    panels={[
                        {
                            key: 'source',
                            header: 'Source',
                            content: (
                                <div className="deprecated-space-y-2">
                                    {sourceLoading && !sourceCode ? (
                                        <LemonSkeleton className="h-24 w-full" />
                                    ) : (
                                        <CodeEditorResizeable
                                            language="typescript"
                                            value={sourceCode}
                                            onChange={(value) => setEditedCode(value ?? '')}
                                            minHeight={160}
                                            embedded
                                        />
                                    )}
                                    {publishDiagnostics.length > 0 ? (
                                        <LemonBanner type="error">
                                            <div className="deprecated-space-y-1">
                                                {publishDiagnostics.map((diagnostic) => (
                                                    <div
                                                        key={`${diagnostic.code}:${diagnostic.path}:${diagnostic.line}:${diagnostic.message}`}
                                                        className="text-xs"
                                                    >
                                                        <LemonTag
                                                            type={
                                                                diagnostic.severity === 'error' ? 'danger' : 'warning'
                                                            }
                                                        >
                                                            {diagnostic.severity}
                                                        </LemonTag>{' '}
                                                        {diagnostic.message}
                                                        {diagnostic.path ? (
                                                            <span className="text-muted">
                                                                {' '}
                                                                ({diagnostic.path}
                                                                {diagnostic.line ? `:${diagnostic.line}` : ''})
                                                            </span>
                                                        ) : null}
                                                    </div>
                                                ))}
                                            </div>
                                        </LemonBanner>
                                    ) : null}
                                    <div className="flex items-center gap-2">
                                        <LemonButton
                                            type="primary"
                                            onClick={() => publishSource()}
                                            loading={publishInFlight}
                                            disabledReason={
                                                publishInFlight
                                                    ? 'A publish is already in progress'
                                                    : !hasSourceChanges
                                                      ? 'No changes to publish'
                                                      : undefined
                                            }
                                        >
                                            Publish changes
                                        </LemonButton>
                                        <LemonButton
                                            onClick={discardSourceChanges}
                                            disabledReason={!hasSourceChanges ? 'No changes to discard' : undefined}
                                        >
                                            Discard
                                        </LemonButton>
                                        {isBuilding ? (
                                            <span className="text-secondary text-xs">Building the canvas…</span>
                                        ) : null}
                                    </div>
                                </div>
                            ),
                        },
                    ]}
                />
            ) : null}
        </div>
    )
}

export const NotebookNodeCanvas = createPostHogWidgetNode<NotebookNodeCanvasAttributes>({
    nodeType: NotebookNodeType.Canvas,
    titlePlaceholder: 'Canvas',
    Component,
    Settings,
    serializedText: (attrs) => getCanvasNameFromPrompt(attrs.prompt ?? '') || 'Canvas',
    heightEstimate: 400,
    minHeight: 100,
    resizeable: true,
    expandable: false,
    href: (attrs) => (attrs.channelId && attrs.id ? urls.codeCanvasLink(attrs.channelId, attrs.id) : undefined),
    attributes: {
        id: { default: '' },
        channelId: {},
        prompt: { default: '' },
    },
})

export function buildCanvasContent(id?: string, channelId?: string, prompt?: string): JSONContent {
    return {
        type: NotebookNodeType.Canvas,
        attrs: { ...(id ? { id } : {}), ...(channelId ? { channelId } : {}), ...(prompt ? { prompt } : {}) },
    }
}
