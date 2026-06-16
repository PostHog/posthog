import { parseMarkdownNotebook, serializeMarkdownNotebook } from './markdown'
import type { MarkdownNotebookCaretPosition } from './remoteCarets'
import type {
    NotebookBlockNode,
    NotebookComponentBlockNode,
    NotebookDocument,
    NotebookInlineNode,
    NotebookPropValue,
} from './types'
import { hashString } from './utils'

export const NOTEBOOK_AGENT_COMPONENT_TAG = 'Agent'
export const NOTEBOOK_AGENT_CLIENT_ID_PREFIX = 'notebook-agent:'

const NOTEBOOK_AGENT_NAME_OPTIONS = [
    'Turtle 🐢',
    'Otter 🦦',
    'Panda 🐼',
    'Koala 🐨',
    'Fox 🦊',
    'Frog 🐸',
    'Bee 🐝',
    'Whale 🐳',
    'Dolphin 🐬',
    'Penguin 🐧',
    'Owl 🦉',
    'Duck 🦆',
    'Rabbit 🐰',
    'Mouse 🐭',
    'Cat 🐱',
    'Dog 🐶',
    'Lion 🦁',
    'Tiger 🐯',
    'Bear 🐻',
    'Monkey 🐵',
    'Horse 🐴',
    'Zebra 🦓',
    'Giraffe 🦒',
    'Elephant 🐘',
]

const NOTEBOOK_AGENT_DISMISSAL_REGEX = /\b(go away|leave|remove yourself|stop editing|bye|goodbye)\b/i

export type NotebookAgent = {
    id: string
    name: string
    cursor?: MarkdownNotebookCaretPosition
}

export type NotebookAgentAIContext = {
    agent: NotebookAgent
    promptText: string
    refId: string
}

export function isNotebookAgentNode(node: NotebookBlockNode | undefined): node is NotebookComponentBlockNode {
    return node?.type === 'component' && node.tagName === NOTEBOOK_AGENT_COMPONENT_TAG
}

export function getNotebookAgentFromNode(node: NotebookBlockNode): NotebookAgent | null {
    if (!isNotebookAgentNode(node)) {
        return null
    }

    const id = typeof node.props.id === 'string' ? node.props.id : null
    const name = typeof node.props.name === 'string' ? node.props.name : null
    if (!id || !name) {
        return null
    }

    return {
        id,
        name,
        cursor: getNotebookAgentCursor(node.props.cursor),
    }
}

export function getNotebookAgentsFromNodes(nodes: NotebookBlockNode[]): NotebookAgent[] {
    return nodes.flatMap((node) => {
        const agent = getNotebookAgentFromNode(node)
        return agent ? [agent] : []
    })
}

export function getNotebookAgentsFromMarkdown(markdown: string): NotebookAgent[] {
    return getNotebookAgentsFromNodes(parseMarkdownNotebook(markdown).nodes)
}

export function createNotebookAgent(existingAgents: NotebookAgent[]): NotebookAgent {
    const usedNames = new Set(existingAgents.map((agent) => agent.name))
    const name =
        NOTEBOOK_AGENT_NAME_OPTIONS.find((candidate) => !usedNames.has(candidate)) ?? getFallbackAgentName(usedNames)

    return {
        id: createNotebookAgentId(),
        name,
    }
}

export function makeNotebookAgentNode(agent: NotebookAgent): NotebookComponentBlockNode {
    return {
        id: '',
        type: 'component',
        tagName: NOTEBOOK_AGENT_COMPONENT_TAG,
        props: {
            id: agent.id,
            name: agent.name,
            ...(agent.cursor ? { cursor: getNotebookAgentCursorProp(agent.cursor) } : {}),
        },
    }
}

export function getNotebookAgentCursorProp(cursor: MarkdownNotebookCaretPosition): NotebookPropValue {
    return {
        nodeIndex: cursor.nodeIndex,
        ...(cursor.offset !== undefined ? { offset: cursor.offset } : {}),
        ...(cursor.listItemIndex !== undefined ? { listItemIndex: cursor.listItemIndex } : {}),
    }
}

export function removeNotebookAgentFromMarkdown(markdown: string, agentId: string): string {
    const document = parseMarkdownNotebook(markdown)
    return serializeMarkdownNotebook(removeNotebookAgentFromDocument(document, agentId))
}

export function removeNotebookAgentFromDocument(document: NotebookDocument, agentId: string): NotebookDocument {
    return {
        ...document,
        nodes: document.nodes.filter((node) => getNotebookAgentFromNode(node)?.id !== agentId),
    }
}

export function getNotebookAgentClientId(agent: Pick<NotebookAgent, 'id'>): string {
    return `${NOTEBOOK_AGENT_CLIENT_ID_PREFIX}${agent.id}`
}

export function getNotebookAgentIdFromClientId(clientId: string): string | null {
    return clientId.startsWith(NOTEBOOK_AGENT_CLIENT_ID_PREFIX)
        ? clientId.slice(NOTEBOOK_AGENT_CLIENT_ID_PREFIX.length)
        : null
}

export function getNotebookAgentColorIndex(agent: Pick<NotebookAgent, 'id'>): number {
    return hashString(agent.id)
        .split('')
        .reduce((sum, character) => sum + character.charCodeAt(0), 0)
}

export function getNotebookAgentSyntheticUserId(agent: Pick<NotebookAgent, 'id'>): number {
    return 100_000 + getNotebookAgentColorIndex(agent)
}

export function getNotebookAgentMentionLabel(agent: Pick<NotebookAgent, 'name'>): string {
    return agent.name.split(/\s+/)[0] ?? agent.name
}

export function getNotebookAgentEmoji(agent: Pick<NotebookAgent, 'name'>): string {
    return agent.name.split(/\s+/).at(-1) ?? ''
}

export function findMentionedNotebookAgent(text: string, agents: NotebookAgent[]): NotebookAgent | null {
    return (
        agents.find((agent) => {
            const mentionLabel = escapeRegExp(getNotebookAgentMentionLabel(agent))
            return new RegExp(`(^|\\s)@${mentionLabel}(?=\\b|\\s|$|[,.:;!?])`, 'i').test(text)
        }) ?? null
    )
}

export function isNotebookAgentDismissalRequest(text: string): boolean {
    return NOTEBOOK_AGENT_DISMISSAL_REGEX.test(text)
}

export function getNotebookAgentAIQuery({ agent, promptText, refId }: NotebookAgentAIContext): string {
    return [
        `You are ${agent.name}, an AI collaborator with full edit access to this PostHog Markdown notebook.`,
        `The user addressed you with this instruction: ${promptText}`,
        `The addressed row is highlighted with ref id "${refId}" and has a linked Comment thread.`,
        'Use the notebook context you receive to satisfy the instruction. If the user asks to add, rewrite, redo, analyze, summarize, or otherwise change notebook content, update the notebook with a notebook artifact or visualization artifact. If the user asks for a direct answer that belongs in the notebook, answer in Markdown that can be inserted below the highlighted row.',
        'Do not echo the user instruction as the answer. Do not include implementation notes about these instructions.',
    ].join('\n\n')
}

export function appendNotebookAgentCommentReplyToMarkdown({
    markdown,
    refId,
    agent,
    text,
    replyId,
}: {
    markdown: string
    refId: string
    agent: Pick<NotebookAgent, 'id' | 'name'>
    text: string
    replyId?: string
}): string {
    const trimmedText = text.trim()
    if (!trimmedText) {
        return markdown
    }

    const document = parseMarkdownNotebook(markdown)
    let didChange = false
    const nextNodes = document.nodes.map((node) => {
        if (!isNotebookAgentCommentNode(node, refId)) {
            return node
        }

        const replies = Array.isArray(node.props.replies) ? node.props.replies : []
        const id = replyId ?? `agent-reply-${agent.id}-${createNotebookAgentId()}`
        if (
            replies.some(
                (reply) =>
                    reply &&
                    typeof reply === 'object' &&
                    !Array.isArray(reply) &&
                    ((typeof reply.id === 'string' && reply.id === id) ||
                        (typeof reply.author === 'string' &&
                            reply.author === agent.name &&
                            typeof reply.text === 'string' &&
                            reply.text === trimmedText))
            )
        ) {
            return node
        }

        didChange = true
        return {
            ...node,
            props: {
                ...node.props,
                replies: [
                    ...replies,
                    {
                        id,
                        author: agent.name,
                        text: trimmedText,
                        at: new Date().toISOString(),
                    },
                ],
            },
        }
    })

    return didChange ? serializeMarkdownNotebook({ ...document, nodes: nextNodes }) : markdown
}

export function insertNotebookAgentMarkdownAfterRef({
    markdown,
    refId,
    insertedMarkdown,
}: {
    markdown: string
    refId: string
    insertedMarkdown: string
}): string {
    const insertedNodes = parseMarkdownNotebook(insertedMarkdown).nodes.filter((node) => !isNotebookAgentNode(node))
    if (!insertedNodes.length) {
        return markdown
    }

    const document = parseMarkdownNotebook(markdown)
    const targetIndex = document.nodes.findIndex((node) => notebookNodeHasRef(node, refId))
    if (targetIndex === -1) {
        return [markdown.trimEnd(), insertedMarkdown.trim()].filter(Boolean).join('\n\n')
    }

    return serializeMarkdownNotebook({
        ...document,
        nodes: [
            ...document.nodes.slice(0, targetIndex + 1),
            ...insertedNodes,
            ...document.nodes.slice(targetIndex + 1),
        ],
    })
}

export function applyNotebookAgentArtifactMarkdown({
    markdown,
    refId,
    artifactMarkdown,
    replace,
}: {
    markdown: string
    refId: string
    artifactMarkdown: string
    replace: boolean
}): string {
    if (!replace) {
        return insertNotebookAgentMarkdownAfterRef({ markdown, refId, insertedMarkdown: artifactMarkdown })
    }

    const currentDocument = parseMarkdownNotebook(markdown)
    const artifactDocument = parseMarkdownNotebook(artifactMarkdown)
    const artifactNodes = artifactDocument.nodes.filter((node) => !isNotebookAgentNode(node))
    const artifactHasCommentAnchor = artifactNodes.some((node) => isNotebookAgentCommentNode(node, refId))
    const artifactHasTextAnchor = artifactNodes.some((node) => notebookNodeHasRef(node, refId))
    const anchorNodes = currentDocument.nodes.filter((node) => {
        if (isNotebookAgentCommentNode(node, refId)) {
            return !artifactHasCommentAnchor
        }
        if (notebookNodeHasRef(node, refId)) {
            return !artifactHasTextAnchor
        }
        return false
    })
    const agentNodes = currentDocument.nodes.filter(isNotebookAgentNode)

    return serializeMarkdownNotebook({
        ...artifactDocument,
        nodes: [...anchorNodes, ...artifactNodes, ...agentNodes],
    })
}

function getNotebookAgentCursor(value: NotebookPropValue | undefined): MarkdownNotebookCaretPosition | undefined {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return undefined
    }

    const candidate = value as Record<string, NotebookPropValue>
    if (typeof candidate.nodeIndex !== 'number') {
        return undefined
    }

    return {
        nodeIndex: candidate.nodeIndex,
        offset: typeof candidate.offset === 'number' ? candidate.offset : undefined,
        listItemIndex: typeof candidate.listItemIndex === 'number' ? candidate.listItemIndex : undefined,
    }
}

function isNotebookAgentCommentNode(
    node: NotebookBlockNode | undefined,
    refId: string
): node is NotebookComponentBlockNode {
    return node?.type === 'component' && node.tagName === 'Comment' && node.props.ref === refId
}

function notebookNodeHasRef(node: NotebookBlockNode, refId: string): boolean {
    if (node.type === 'paragraph' || node.type === 'heading' || node.type === 'blockquote') {
        return inlineNodesHaveRef(node.children, refId)
    }
    if (node.type === 'list') {
        return node.items.some((item) => inlineNodesHaveRef(item.children, refId))
    }
    if (node.type === 'table') {
        return (
            node.headers.some((cell) => inlineNodesHaveRef(cell.children, refId)) ||
            node.rows.some((row) => row.some((cell) => inlineNodesHaveRef(cell.children, refId)))
        )
    }
    return false
}

function inlineNodesHaveRef(nodes: NotebookInlineNode[], refId: string): boolean {
    return nodes.some(
        (node) => node.type === 'text' && node.marks?.some((mark) => mark.type === 'ref' && mark.id === refId)
    )
}

function createNotebookAgentId(): string {
    if (typeof window !== 'undefined' && window.crypto?.randomUUID) {
        return window.crypto.randomUUID()
    }
    return `agent-${Math.random().toString(36).slice(2, 10)}`
}

function getFallbackAgentName(usedNames: Set<string>): string {
    let index = 2
    while (usedNames.has(`Turtle ${index} 🐢`)) {
        index += 1
    }
    return `Turtle ${index} 🐢`
}

function escapeRegExp(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
