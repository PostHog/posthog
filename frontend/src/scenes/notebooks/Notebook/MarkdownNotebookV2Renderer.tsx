import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { MarkdownNotebook } from 'lib/components/MarkdownNotebook'
import type { MarkdownNotebookAskAIRequest } from 'lib/components/MarkdownNotebook'
import { uuid } from 'lib/utils'

import { type NotebookArtifactContent } from '~/queries/schema/schema-assistant-messages'

import { InlineNotebookAIRunner } from './MarkdownNotebookAIChat'
import { NOTEBOOK_MARKDOWN_REGISTRY } from './markdownNotebookRegistry'
import {
    InlineNotebookAIRequest,
    MarkdownNotebookRuntimeContext,
    MarkdownNotebookRuntimeContextValue,
    NotebookArtifactApplyMode,
    getInlineNotebookAIPanelId,
    getNotebookAIChatUIContext,
    insertMarkdownAfterNotebookAIChatMarker,
    preserveNotebookAIChatMarker,
} from './markdownNotebookRuntime'
import {
    buildMarkdownNotebookContent,
    getMarkdownNotebookMarkdown,
    getMarkdownNotebookNodeId,
    notebookArtifactContentToMarkdown,
} from './markdownNotebookV2'
import { notebookLogic } from './notebookLogic'

export function MarkdownNotebookV2(): JSX.Element {
    const { content, isEditable, notebook } = useValues(notebookLogic)
    const { setLocalContent, setAutosavePaused } = useActions(notebookLogic)
    const markdown = getMarkdownNotebookMarkdown(content)
    const remoteMarkdown = getMarkdownNotebookMarkdown(notebook?.content)
    const nodeId = getMarkdownNotebookNodeId(content)
    const [isInteractionActive, setIsInteractionActive] = useState(false)
    const [draftMarkdown, setDraftMarkdown] = useState<string | null>(null)
    const [inlineAIRequests, setInlineAIRequests] = useState<InlineNotebookAIRequest[]>([])
    const isInteractionActiveRef = useRef(false)
    const latestMarkdownRef = useRef(markdown)
    const bufferedMarkdownRef = useRef<string | null>(null)
    const nodeIdRef = useRef(nodeId)
    const renderedMarkdown = draftMarkdown ?? markdown

    useEffect(() => {
        if (draftMarkdown === null) {
            latestMarkdownRef.current = markdown
        } else if (draftMarkdown === markdown) {
            latestMarkdownRef.current = markdown
            setDraftMarkdown(null)
        }
    }, [markdown, draftMarkdown])

    useEffect(() => {
        nodeIdRef.current = nodeId
    }, [nodeId])

    const flushBufferedMarkdown = useCallback((): void => {
        const bufferedMarkdown = bufferedMarkdownRef.current
        if (bufferedMarkdown === null) {
            return
        }

        bufferedMarkdownRef.current = null
        if (bufferedMarkdown === latestMarkdownRef.current) {
            return
        }

        latestMarkdownRef.current = bufferedMarkdown
        setLocalContent(buildMarkdownNotebookContent(bufferedMarkdown, nodeIdRef.current))
    }, [setLocalContent])

    const handleChange = useCallback(
        (nextMarkdown: string): void => {
            if (isInteractionActiveRef.current) {
                bufferedMarkdownRef.current = nextMarkdown
                setDraftMarkdown(nextMarkdown)
                return
            }

            if (nextMarkdown === latestMarkdownRef.current) {
                return
            }

            latestMarkdownRef.current = nextMarkdown
            setLocalContent(buildMarkdownNotebookContent(nextMarkdown, nodeIdRef.current))
        },
        [setLocalContent]
    )
    const handleInteractionStateChange = useCallback(
        (nextIsInteractionActive: boolean): void => {
            if (isInteractionActiveRef.current === nextIsInteractionActive) {
                return
            }

            isInteractionActiveRef.current = nextIsInteractionActive
            setIsInteractionActive(nextIsInteractionActive)
            if (nextIsInteractionActive) {
                setDraftMarkdown(latestMarkdownRef.current)
                setAutosavePaused(true)
                return
            }

            const hadBufferedMarkdown = bufferedMarkdownRef.current !== null
            flushBufferedMarkdown()
            if (!hadBufferedMarkdown) {
                setDraftMarkdown(null)
            }
            setAutosavePaused(false)
        },
        [flushBufferedMarkdown, setAutosavePaused]
    )
    const handleAskAI = useCallback(
        ({
            chatId,
            query,
            source,
            chatNodeId,
            chatMarker,
            markdown,
            markdownWithChat,
            selectedMarkdown,
        }: MarkdownNotebookAskAIRequest): void => {
            const uiContext = getNotebookAIChatUIContext({
                notebookShortId: notebook?.short_id ?? null,
                notebookTitle: notebook?.title ?? 'Untitled notebook',
                markdown: markdownWithChat,
                chatId,
                chatMarker,
            })

            const inlineAIRequest: InlineNotebookAIRequest = {
                chatId,
                panelId: getInlineNotebookAIPanelId(chatId, 'inline'),
                query,
                source,
                chatNodeId,
                chatMarker,
                markdown,
                markdownWithChat,
                selectedMarkdown,
                uiContext,
            }
            setInlineAIRequests((currentRequests) => [
                ...currentRequests.filter((currentRequest) => currentRequest.chatId !== chatId),
                inlineAIRequest,
            ])
        },
        [notebook?.short_id, notebook?.title]
    )

    const applyNotebookArtifactContent = useCallback(
        (content: NotebookArtifactContent, chatId?: string, mode: NotebookArtifactApplyMode = 'replace'): void => {
            const artifactMarkdown = notebookArtifactContentToMarkdown(content)
            if (!artifactMarkdown.trim()) {
                return
            }

            const nextMarkdown =
                mode === 'insert-after-chat'
                    ? insertMarkdownAfterNotebookAIChatMarker(artifactMarkdown, latestMarkdownRef.current, chatId)
                    : preserveNotebookAIChatMarker(artifactMarkdown, latestMarkdownRef.current, chatId)
            if (nextMarkdown === latestMarkdownRef.current) {
                return
            }

            bufferedMarkdownRef.current = null
            latestMarkdownRef.current = nextMarkdown
            setDraftMarkdown(null)
            setAutosavePaused(false)
            setLocalContent(buildMarkdownNotebookContent(nextMarkdown, nodeIdRef.current))
        },
        [setAutosavePaused, setLocalContent]
    )

    const runtimeContext = useMemo<MarkdownNotebookRuntimeContextValue>(
        () => ({
            notebookShortId: notebook?.short_id ?? null,
            notebookTitle: notebook?.title ?? 'Untitled notebook',
            markdown: renderedMarkdown,
            applyNotebookArtifactContent,
        }),
        [applyNotebookArtifactContent, notebook?.short_id, notebook?.title, renderedMarkdown]
    )

    const handleInlineAIComplete = useCallback((request: InlineNotebookAIRequest): void => {
        window.setTimeout(() => {
            setInlineAIRequests((currentRequests) =>
                currentRequests.filter((currentRequest) => currentRequest.chatId !== request.chatId)
            )
        }, 0)
    }, [])

    const handleInlineAIError = useCallback((request: InlineNotebookAIRequest): void => {
        setInlineAIRequests((currentRequests) =>
            currentRequests.filter((currentRequest) => currentRequest.chatId !== request.chatId)
        )
    }, [])

    return (
        <MarkdownNotebookRuntimeContext.Provider value={runtimeContext}>
            <MarkdownNotebook
                value={renderedMarkdown}
                remoteValue={remoteMarkdown}
                mode={isEditable ? 'edit' : 'view'}
                registry={NOTEBOOK_MARKDOWN_REGISTRY}
                onChange={isEditable ? handleChange : undefined}
                onAskAI={isEditable ? handleAskAI : undefined}
                createAIChatId={uuid}
                deferRemoteValue={isInteractionActive}
                onInteractionStateChange={handleInteractionStateChange}
                className="Notebook__markdown-v2"
                data-attr="notebook-markdown-v2"
                autoFocus={isEditable}
                showDebug={isEditable}
            />
            {inlineAIRequests.map((request) => (
                <InlineNotebookAIRunner
                    key={request.chatId}
                    request={request}
                    onComplete={handleInlineAIComplete}
                    onError={handleInlineAIError}
                />
            ))}
        </MarkdownNotebookRuntimeContext.Provider>
    )
}
