import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { LemonBanner, LemonButton, LemonInput, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

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
import { CANVAS_COMPONENT_PATH, getCanvasNameFromPrompt, notebookNodeCanvasLogic } from './notebookNodeCanvasLogic'

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
        return <EmptyStateMessage>The agent is creating this canvas.</EmptyStateMessage>
    }

    if (canvasCreationError) {
        return (
            <EmptyStateMessage>
                <div className="deprecated-space-y-2">
                    <div>Couldn't create the canvas: {canvasCreationError}</div>
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
        canvasLoading,
        nameValue,
        contextValue,
        hasMetaChanges,
        agentInstruction,
        askingAgent,
        sourceLoading,
        sourceCode,
        hasSourceChanges,
        publishResultLoading,
        isBuilding,
        publishDiagnostics,
        creatingCanvas,
    } = useValues(logic)
    const {
        discardSourceChanges,
        loadSource,
        setEditedCode,
        publishSource,
        setEditedName,
        setEditedContext,
        saveCanvasMeta,
        setAgentInstruction,
        askAgent,
        createFromPrompt,
    } = useActions(logic)

    useEffect(() => {
        if (id) {
            loadSource()
        }
        // oxlint-disable-next-line exhaustive-deps
    }, [id])

    const publishInFlight = publishResultLoading || isBuilding

    return (
        <div className="p-3 deprecated-space-y-2">
            <div className="flex-1">
                <LemonLabel info="The original request stays with this notebook block. A prompt without a canvas ID creates a new canvas.">
                    Prompt
                </LemonLabel>
                <LemonTextArea
                    value={prompt}
                    onChange={(value) => updateAttributes({ prompt: value || undefined })}
                    placeholder="Describe the canvas to create, for example: a spinning 3D globe showing signups by country."
                    minRows={id ? 3 : 8}
                    autoFocus={wasNotebookNodeJustInserted(attributes.nodeId)}
                />
            </div>
            {id ? (
                <>
                    <div className="flex gap-2">
                        <div className="flex-1">
                            <LemonLabel>Canvas ID</LemonLabel>
                            <LemonInput
                                value={id}
                                onChange={(value) => updateAttributes({ id: value })}
                                placeholder="Canvas UUID"
                            />
                        </div>
                        <div className="flex-1">
                            <LemonLabel>Channel ID</LemonLabel>
                            <LemonInput
                                value={attributes.channelId ?? ''}
                                onChange={(value) => updateAttributes({ channelId: value || undefined })}
                                placeholder="Channel UUID (optional)"
                            />
                        </div>
                    </div>
                    <div className="flex-1">
                        <LemonLabel>Name</LemonLabel>
                        <LemonInput value={nameValue} onChange={setEditedName} placeholder="Canvas name" />
                    </div>
                    <div className="flex-1">
                        <LemonLabel info="What this canvas should show. The agent reads these instructions whenever it builds or updates the canvas.">
                            Agent instructions
                        </LemonLabel>
                        <LemonTextArea
                            value={contextValue}
                            onChange={setEditedContext}
                            placeholder="Describe what this canvas should show, for example: a weekly growth overview with signups, activation, and top referrers."
                            minRows={3}
                        />
                    </div>
                    <LemonButton
                        type="secondary"
                        onClick={() => saveCanvasMeta()}
                        loading={canvasLoading}
                        disabledReason={canvasLoading ? 'Saving' : !hasMetaChanges ? 'No changes to save' : undefined}
                    >
                        Save name and instructions
                    </LemonButton>
                    <div className="flex-1">
                        <LemonLabel info="Starts an agent task in the canvas's channel. The agent edits the canvas source and publishes a new build; the rendered page updates when it lands.">
                            Ask the agent
                        </LemonLabel>
                        <LemonTextArea
                            value={agentInstruction}
                            onChange={setAgentInstruction}
                            placeholder="Describe the change, for example: add a weekly signups chart split by plan."
                            minRows={2}
                        />
                    </div>
                    <LemonButton
                        type="primary"
                        onClick={() => askAgent()}
                        loading={askingAgent}
                        disabledReason={
                            askingAgent
                                ? 'Starting the agent'
                                : !agentInstruction.trim()
                                  ? 'Describe the change first'
                                  : undefined
                        }
                    >
                        Send to agent
                    </LemonButton>
                    <LemonLabel info="Publishing creates a new source version and rebuilds the page. The rendered canvas updates when the build is ready.">
                        Source ({CANVAS_COMPONENT_PATH})
                    </LemonLabel>
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
                                        <LemonTag type={diagnostic.severity === 'error' ? 'danger' : 'warning'}>
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
                        {isBuilding ? <span className="text-secondary text-xs">Building the canvas…</span> : null}
                    </div>
                </>
            ) : (
                <LemonButton
                    type="primary"
                    onClick={() => createFromPrompt()}
                    loading={creatingCanvas}
                    disabledReason={
                        creatingCanvas ? 'Creating the canvas' : !prompt.trim() ? 'Add a prompt first' : undefined
                    }
                >
                    Create canvas
                </LemonButton>
            )}
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
