import { Extension, Node, type NodeViewProps, mergeAttributes } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer, getExtensionField } from '@tiptap/react'
import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { IconRefresh, IconSparkles } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import {
    EditorCommands,
    EditorRange,
    JSONContent,
    RichContentEditorType,
    RichContentNode,
    TTEditor,
} from 'lib/components/RichContentEditor/types'
import { uuid } from 'lib/utils'
import { maxContextLogic } from 'scenes/max/maxContextLogic'
import { maxLogic } from 'scenes/max/maxLogic'
import { maxThreadLogic, type ThreadMessage } from 'scenes/max/maxThreadLogic'
import type { MaxNotebookRequestLocationContext } from 'scenes/max/maxTypes'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { AssistantMessageType } from '~/queries/schema/schema-assistant-messages'
import { SidePanelTab } from '~/types'

import { NotebookNodeType } from '../types'
import { textContent } from '../utils'

const NOTEBOOK_AI_PROMPT_LABEL = 'Ask PostHog AI:'
const NOTEBOOK_AI_PLACEHOLDER_TEXT = 'Thinking...'
const MAX_REQUEST_LOCATION_BLOCK_TEXT_LENGTH = 500

type NotebookAIPromptOptions = {
    shortId: string
    title?: string | null
}

type InsertNotebookAIPromptOptions = {
    insertAsParagraph?: boolean
}

type NotebookAIPromptStatusAttrs = {
    prompt?: string
}

type NotebookAIAttrs = {
    id?: string | null
}

function NotebookAIPromptComponent(): JSX.Element {
    return (
        <NodeViewWrapper as="span" className="NotebookAIPrompt" contentEditable={false}>
            <IconSparkles className="NotebookAIPrompt__icon" />
            <span>{NOTEBOOK_AI_PROMPT_LABEL}</span>
        </NodeViewWrapper>
    )
}

function NotebookAIComponent(props: NodeViewProps): JSX.Element {
    const { deleteNode } = props
    const { activeStreamingThreads, threadLogicKey } = useValues(maxLogic({ tabId: 'sidepanel' }))
    const threadLogic = maxThreadLogic({ tabId: 'sidepanel', conversationId: threadLogicKey })
    const { streamingActive, threadRaw } = useValues(threadLogic)
    const { retryLastMessage } = useActions(threadLogic)
    const isStreaming = activeStreamingThreads > 0 || streamingActive
    const hasSeenStreaming = useRef(isStreaming)
    const [retryRequested, setRetryRequested] = useState(false)
    const hasRetriableFailure = hasSeenStreaming.current && !isStreaming && hasRetriableMaxFailure(threadRaw)

    useEffect(() => {
        if (isStreaming) {
            hasSeenStreaming.current = true
            setRetryRequested(false)
            return
        }

        if (hasSeenStreaming.current && !hasRetriableFailure) {
            deleteNode()
        }
    }, [deleteNode, hasRetriableFailure, isStreaming])

    if (hasRetriableFailure) {
        return (
            <NodeViewWrapper className="NotebookAI NotebookAI--failed" contentEditable={false}>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    icon={<IconRefresh />}
                    loading={retryRequested}
                    disabled={retryRequested}
                    onClick={() => {
                        setRetryRequested(true)
                        retryLastMessage()
                    }}
                >
                    Retry
                </LemonButton>
            </NodeViewWrapper>
        )
    }

    return (
        <NodeViewWrapper className="NotebookAI" contentEditable={false}>
            <Spinner textColored className="NotebookAI__spinner" />
            <span>{NOTEBOOK_AI_PLACEHOLDER_TEXT}</span>
        </NodeViewWrapper>
    )
}

export function hasRetriableMaxFailure(threadRaw: ThreadMessage[]): boolean {
    const lastNonHumanMessage = [...threadRaw].reverse().find((message) => message.type !== AssistantMessageType.Human)

    return !!(
        lastNonHumanMessage &&
        (lastNonHumanMessage.status === 'error' || lastNonHumanMessage.type === AssistantMessageType.Failure)
    )
}

function NotebookAIPromptStatusComponent(props: NodeViewProps): JSX.Element {
    const { sidePanelOpen, selectedTab, selectedTabOptions } = useValues(sidePanelStateLogic)
    const { prompt = '' } = props.node.attrs as NotebookAIPromptStatusAttrs

    if (sidePanelOpen && selectedTab === SidePanelTab.Max) {
        return <NotebookAIPromptStatusWithMax prompt={prompt} selectedTabOptions={selectedTabOptions} />
    }

    return <NotebookAIPromptSubmittedStatus prompt={prompt} />
}

function NotebookAIPromptStatusWithMax({
    prompt,
    selectedTabOptions,
}: {
    prompt: string
    selectedTabOptions: string | null
}): JSX.Element {
    const { activeStreamingThreads } = useValues(maxLogic({ tabId: 'sidepanel' }))

    if (activeStreamingThreads > 0 && getQuestionFromSidePanelOptions(selectedTabOptions) === prompt.trim()) {
        return <NotebookAIPromptThinkingStatus />
    }

    return <NotebookAIPromptSubmittedStatus prompt={prompt} />
}

function NotebookAIPromptThinkingStatus(): JSX.Element {
    return (
        <NodeViewWrapper as="span" className="NotebookAIPromptStatus" contentEditable={false}>
            <Spinner textColored className="NotebookAIPromptStatus__spinner" />
            <span>Thinking...</span>
        </NodeViewWrapper>
    )
}

function NotebookAIPromptSubmittedStatus({ prompt }: { prompt: string }): JSX.Element {
    return (
        <NodeViewWrapper as="span" className="NotebookAIPromptSubmitted" contentEditable={false}>
            <span className="NotebookAIPrompt">
                <IconSparkles className="NotebookAIPrompt__icon" />
                <span>{NOTEBOOK_AI_PROMPT_LABEL}</span>
            </span>
            {prompt ? <span className="NotebookAIPromptSubmitted__question">{prompt}</span> : null}
            <span className="NotebookAIPromptStatus">Asked in side panel</span>
        </NodeViewWrapper>
    )
}

export const NotebookAI = Node.create({
    name: NotebookNodeType.AI,
    group: 'block',
    atom: true,
    selectable: false,
    draggable: false,

    serializedText: (attrs: NotebookAIAttrs): string => buildNotebookAIText(attrs.id),

    extendNodeSchema(extension) {
        const context = {
            name: extension.name,
            options: extension.options,
            storage: extension.storage,
        }
        return {
            serializedText: getExtensionField(extension, 'serializedText', context),
        }
    },

    addAttributes() {
        return {
            id: { default: null },
        }
    },

    parseHTML() {
        return [{ tag: NotebookNodeType.AI }]
    },

    renderHTML({ HTMLAttributes }) {
        return [NotebookNodeType.AI, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(NotebookAIComponent)
    },
})

export const NotebookAIPrompt = Node.create({
    name: NotebookNodeType.AIPrompt,
    inline: true,
    group: 'inline',
    atom: true,
    selectable: false,

    serializedText: () => NOTEBOOK_AI_PROMPT_LABEL,

    parseHTML() {
        return [{ tag: NotebookNodeType.AIPrompt }]
    },

    renderHTML({ HTMLAttributes }) {
        return [NotebookNodeType.AIPrompt, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(NotebookAIPromptComponent)
    },
})

export const NotebookAIPromptStatus = Node.create({
    name: NotebookNodeType.AIPromptStatus,
    inline: true,
    group: 'inline',
    atom: true,
    selectable: false,

    serializedText: (attrs: NotebookAIPromptStatusAttrs): string =>
        attrs.prompt ? `${NOTEBOOK_AI_PROMPT_LABEL} ${attrs.prompt}` : '',

    addAttributes() {
        return {
            prompt: { default: '' },
        }
    },

    parseHTML() {
        return [{ tag: NotebookNodeType.AIPromptStatus }]
    },

    renderHTML({ HTMLAttributes }) {
        return [NotebookNodeType.AIPromptStatus, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(NotebookAIPromptStatusComponent)
    },
})

export function insertNotebookAIPrompt(
    editor: Pick<RichContentEditorType, 'chain'>,
    position: number | EditorRange,
    { insertAsParagraph = false }: InsertNotebookAIPromptOptions = {}
): void {
    insertNotebookAIPromptIntoChain(editor.chain(), position, { insertAsParagraph }).run()
}

export function insertNotebookAIPromptIntoChain(
    chain: EditorCommands,
    position: number | EditorRange,
    { insertAsParagraph = false }: InsertNotebookAIPromptOptions = {}
): EditorCommands {
    const content = insertAsParagraph
        ? {
              type: 'paragraph',
              content: buildNotebookAIPromptInlineContent(),
          }
        : buildNotebookAIPromptInlineContent()

    return chain
        .insertContentAt(position, content)
        .setTextSelection(promptSelectionPosition(position, insertAsParagraph))
}

export function buildSubmittedNotebookAIPromptContent(prompt: string): JSONContent[] {
    return [{ type: NotebookNodeType.AIPromptStatus, attrs: { prompt: prompt.trim() } }]
}

export function buildNotebookAIContent(id: string = uuid()): JSONContent {
    return { type: NotebookNodeType.AI, attrs: { id } }
}

export function submitNotebookAIPromptFromRange(
    editor: Pick<RichContentEditorType, 'chain' | 'getAdjacentNodes'>,
    range: EditorRange,
    prompt: string,
    options: NotebookAIPromptOptions
): void {
    const placeholderId = uuid()
    const placeholderText = buildNotebookAIText(placeholderId)

    addNotebookContext(editor, range.from, options, placeholderText)
    editor.chain().insertContentAt(range, buildNotebookAIContent(placeholderId)).run()
    sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, `!${prompt}`)
}

export const NotebookAIPromptExtension = Extension.create<NotebookAIPromptOptions>({
    name: 'notebook-ai-prompt-extension',
    priority: 250,

    addOptions() {
        return {
            shortId: '',
            title: null,
        }
    },

    addKeyboardShortcuts() {
        return {
            Enter: () => submitActiveNotebookAIPrompt(this.editor, this.options),
        }
    },
})

function buildNotebookAIPromptInlineContent(): JSONContent[] {
    return [{ type: NotebookNodeType.AIPrompt }, { type: 'text', text: ' ' }]
}

function buildNotebookAIText(id?: string | null): string {
    const idAttribute = id ? ` id="${escapeAttribute(id)}"` : ''
    return `<AI${idAttribute}>${NOTEBOOK_AI_PLACEHOLDER_TEXT}</AI>`
}

function escapeAttribute(value: string): string {
    return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function getQuestionFromSidePanelOptions(options: string | null): string {
    if (!options) {
        return ''
    }

    let remaining = options
    if (remaining.startsWith('mode=')) {
        const colonIndex = remaining.indexOf(':', 5)
        remaining = colonIndex === -1 ? '' : remaining.slice(colonIndex + 1)
    }

    return remaining.startsWith('!') ? remaining.slice(1).trim() : remaining.trim()
}

function promptSelectionPosition(position: number | EditorRange, insertAsParagraph: boolean): number {
    const from = typeof position === 'number' ? position : position.from
    return from + (insertAsParagraph ? 3 : 2)
}

function submitActiveNotebookAIPrompt(editor: TTEditor, options: NotebookAIPromptOptions): boolean {
    const { selection } = editor.state

    if (!selection.empty) {
        return false
    }

    const { $from } = selection
    const paragraph = $from.parent

    if (paragraph.type.name !== 'paragraph' || paragraph.firstChild?.type.name !== NotebookNodeType.AIPrompt) {
        return false
    }

    const prompt = getPromptTextFromAIPromptParagraph(paragraph)
    if (!prompt) {
        return true
    }

    const from = $from.before($from.depth)
    const to = $from.after($from.depth)
    const placeholderId = uuid()
    const placeholderText = buildNotebookAIText(placeholderId)

    addNotebookContextFromTiptap(editor, $from.index(0), from, options, placeholderText)

    editor.chain().focus().insertContentAt({ from, to }, buildNotebookAIContent(placeholderId)).run()

    sidePanelStateLogic.actions.openSidePanel(SidePanelTab.Max, `!${prompt}`)
    return true
}

function getPromptTextFromAIPromptParagraph(node: RichContentNode): string {
    let text = ''
    let afterPromptLabel = false

    node.forEach((child) => {
        if (child.type.name === NotebookNodeType.AIPrompt) {
            afterPromptLabel = true
            return
        }

        if (child.type.name === NotebookNodeType.AIPromptStatus) {
            return
        }

        if (afterPromptLabel) {
            text += child.textContent
        }
    })

    return text.trim()
}

function addNotebookContext(
    editor: Pick<RichContentEditorType, 'getAdjacentNodes'>,
    position: number,
    options: NotebookAIPromptOptions,
    currentBlockText: string
): void {
    const { previous, next } = editor.getAdjacentNodes(position)
    addOrUpdateContextNotebook({
        short_id: options.shortId,
        title: options.title,
        request_location: {
            type: 'notebook_position',
            position,
            current_block_text: currentBlockText,
            previous_block_text: getAnchorText(previous),
            next_block_text: getAnchorText(next),
        },
    })
}

function addNotebookContextFromTiptap(
    editor: TTEditor,
    currentBlockIndex: number,
    position: number,
    options: NotebookAIPromptOptions,
    currentBlockText: string
): void {
    const { doc } = editor.state
    addOrUpdateContextNotebook({
        short_id: options.shortId,
        title: options.title,
        request_location: {
            type: 'notebook_position',
            position,
            current_block_text: currentBlockText,
            previous_block_text: getAnchorText(doc.maybeChild(currentBlockIndex - 1)),
            next_block_text: getAnchorText(doc.maybeChild(currentBlockIndex + 1)),
        },
    })
}

function addOrUpdateContextNotebook(data: {
    short_id: string
    title?: string | null
    request_location?: MaxNotebookRequestLocationContext
}): void {
    const logic = maxContextLogic()
    if (!logic.isMounted()) {
        logic.mount()
    }
    logic.actions.addOrUpdateContextNotebook(data)
}

function getAnchorText(node: RichContentNode | null): string | null {
    if (!node) {
        return null
    }

    const content = textContent(node).trim()
    if (!content) {
        return null
    }
    if (content.length <= MAX_REQUEST_LOCATION_BLOCK_TEXT_LENGTH) {
        return content
    }
    return `${content.slice(0, MAX_REQUEST_LOCATION_BLOCK_TEXT_LENGTH).trimEnd()}...`
}
