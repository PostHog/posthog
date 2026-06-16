import { parseMarkdownNotebook, serializeMarkdownNotebook } from './markdown'
import type { MarkdownNotebookCaretPosition } from './remoteCarets'
import type {
    NotebookBlockNode,
    NotebookComponentBlockNode,
    NotebookDocument,
    NotebookInlineNode,
    NotebookPropValue,
    NotebookTextBlockNode,
} from './types'
import { getInlineText, getNodeFingerprint, hashString } from './utils'

export const NOTEBOOK_AGENT_COMPONENT_TAG = 'Agent'
export const NOTEBOOK_AGENT_CLIENT_ID_PREFIX = 'notebook-agent:'
export const NOTEBOOK_AI_AGENT_ID = 'ai'
export const NOTEBOOK_AI_AGENT_NAME = 'AI'
export const NOTEBOOK_AI_WRITING_PLACEHOLDER = 'Thinking...'

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
        return agent?.id === NOTEBOOK_AI_AGENT_ID ? [{ ...agent, name: NOTEBOOK_AI_AGENT_NAME }] : []
    })
}

export function getNotebookAgentsFromMarkdown(markdown: string): NotebookAgent[] {
    return getNotebookAgentsFromNodes(parseMarkdownNotebook(markdown).nodes)
}

export function createNotebookAgent(_existingAgents: NotebookAgent[] = []): NotebookAgent {
    return {
        id: NOTEBOOK_AI_AGENT_ID,
        name: NOTEBOOK_AI_AGENT_NAME,
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

export function preserveNotebookAIAgentNode(nextMarkdown: string, currentMarkdown: string): string {
    const currentDocument = parseMarkdownNotebook(currentMarkdown)
    const currentAIAgentNode = currentDocument.nodes.find(
        (node) => getNotebookAgentFromNode(node)?.id === NOTEBOOK_AI_AGENT_ID
    )
    if (!currentAIAgentNode) {
        return nextMarkdown
    }

    const nextDocument = parseMarkdownNotebook(nextMarkdown)
    if (nextDocument.nodes.some((node) => getNotebookAgentFromNode(node)?.id === NOTEBOOK_AI_AGENT_ID)) {
        return nextMarkdown
    }

    return serializeMarkdownNotebook({
        ...nextDocument,
        nodes: [...nextDocument.nodes, currentAIAgentNode],
    })
}

export function normalizeNotebookAIAgentArtifactMarkdown(artifactMarkdown: string, currentMarkdown: string): string {
    const currentDocument = parseMarkdownNotebook(currentMarkdown)
    const currentAgentIndex = currentDocument.nodes.findIndex(
        (node) => getNotebookAgentFromNode(node)?.id === NOTEBOOK_AI_AGENT_ID
    )
    if (currentAgentIndex === -1) {
        return artifactMarkdown
    }

    const agent = getNotebookAgentFromNode(currentDocument.nodes[currentAgentIndex])
    const cursorIndex = getNotebookAIAgentTargetIndex(
        currentDocument.nodes,
        agent?.cursor?.nodeIndex,
        currentAgentIndex
    )
    const cursorNode = currentDocument.nodes[cursorIndex]
    if (!cursorNode || isNotebookAgentNode(cursorNode)) {
        return artifactMarkdown
    }

    const artifactDocument = parseMarkdownNotebook(artifactMarkdown)
    const artifactNodes = artifactDocument.nodes.filter((node) => !isNotebookAgentNode(node))
    const prefixNodes = currentDocument.nodes.slice(0, cursorIndex).filter((node) => !isNotebookAgentNode(node))
    if (!prefixNodes.length || !nodesStartWith(artifactNodes, prefixNodes)) {
        return artifactMarkdown
    }

    const tailNodes = stripNotebookAIAgentEchoFromTail(artifactNodes.slice(prefixNodes.length), prefixNodes, cursorNode)
    const nextNodes = [...prefixNodes, ...tailNodes]
    if (nodesHaveSameFingerprints(nextNodes, artifactNodes)) {
        return artifactMarkdown
    }

    return serializeMarkdownNotebook({
        ...artifactDocument,
        nodes: nextNodes,
    })
}

export function replaceNotebookAIAgentCursorMarkdown(
    markdown: string,
    replacementMarkdown: string,
    replacedNodeCount: number = 1
): string {
    return applyNotebookAIAgentCursorMarkdown(markdown, replacementMarkdown, 'replace', replacedNodeCount)
}

export function insertMarkdownAfterNotebookAIAgentCursor(markdown: string, insertedMarkdown: string): string {
    return applyNotebookAIAgentCursorMarkdown(markdown, insertedMarkdown, 'insert-after')
}

export function insertNotebookAIFollowUpPromptAfterCursor(markdown: string, promptMarkdown: string): string {
    const trimmedPromptMarkdown = promptMarkdown.trim()
    if (!trimmedPromptMarkdown || markdown.includes(trimmedPromptMarkdown)) {
        return markdown
    }

    const document = parseMarkdownNotebook(markdown)
    const agentIndex = document.nodes.findIndex((node) => getNotebookAgentFromNode(node)?.id === NOTEBOOK_AI_AGENT_ID)
    if (agentIndex === -1) {
        return markdown
    }

    const promptNodes = parseMarkdownNotebook(trimmedPromptMarkdown).nodes.filter(
        (node) => getNotebookAgentFromNode(node)?.id !== NOTEBOOK_AI_AGENT_ID
    )
    if (!promptNodes.length) {
        return markdown
    }

    const agent = getNotebookAgentFromNode(document.nodes[agentIndex])
    const cursorIndex = getNotebookAIAgentTargetIndex(document.nodes, agent?.cursor?.nodeIndex, agentIndex)
    const insertionIndex = cursorIndex + 1
    const nextNodes = [
        ...document.nodes.slice(0, insertionIndex),
        ...promptNodes,
        ...document.nodes.slice(insertionIndex),
    ]

    return serializeMarkdownNotebook({
        ...document,
        nodes: updateNotebookAIAgentCursor(nextNodes, getNotebookNodeEndCursor(nextNodes[cursorIndex], cursorIndex)),
    })
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

export function getNotebookAgentAvatarLabel(agent: Pick<NotebookAgent, 'name'>): string {
    return (agent.name.trim().split(/\s+/)[0] || NOTEBOOK_AI_AGENT_NAME).slice(0, 2).toUpperCase()
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
    const insertedNodes = parseMarkdownNotebook(normalizeNotebookAIInsertedMarkdown(insertedMarkdown)).nodes.filter(
        (node) => !isNotebookAgentNode(node)
    )
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

function applyNotebookAIAgentCursorMarkdown(
    markdown: string,
    insertedMarkdown: string,
    mode: 'replace' | 'insert-after',
    replacedNodeCount: number = 1
): string {
    const trimmedInsertedMarkdown = normalizeNotebookAIInsertedMarkdown(insertedMarkdown).trim()
    if (!trimmedInsertedMarkdown || (mode === 'insert-after' && markdown.includes(trimmedInsertedMarkdown))) {
        return markdown
    }

    const document = parseMarkdownNotebook(markdown)
    const agentIndex = document.nodes.findIndex((node) => getNotebookAgentFromNode(node)?.id === NOTEBOOK_AI_AGENT_ID)
    if (agentIndex === -1) {
        return markdown
    }

    const parsedReplacementNodes = parseMarkdownNotebook(trimmedInsertedMarkdown).nodes.filter(
        (node) => getNotebookAgentFromNode(node)?.id !== NOTEBOOK_AI_AGENT_ID
    )
    if (!parsedReplacementNodes.length) {
        return markdown
    }

    const agent = getNotebookAgentFromNode(document.nodes[agentIndex])
    const cursorIndex = getNotebookAIAgentTargetIndex(document.nodes, agent?.cursor?.nodeIndex, agentIndex)
    const replacementNodes = stripEchoedNotebookContextBeforeAICursor(
        document.nodes,
        cursorIndex,
        parsedReplacementNodes
    )
    if (!replacementNodes.length) {
        return markdown
    }
    const targetRange =
        mode === 'replace'
            ? getNotebookAIAgentReplaceRange(document.nodes, cursorIndex, replacedNodeCount)
            : { insertionIndex: cursorIndex + 1, deleteCount: 0 }
    const { insertionIndex, deleteCount } = targetRange
    const nextNodes = [
        ...document.nodes.slice(0, insertionIndex),
        ...replacementNodes,
        ...document.nodes.slice(insertionIndex + deleteCount),
    ]
    const cursorNodeIndex = insertionIndex + replacementNodes.length - 1

    return serializeMarkdownNotebook({
        ...document,
        nodes: updateNotebookAIAgentCursor(
            nextNodes,
            getNotebookNodeEndCursor(nextNodes[cursorNodeIndex], cursorNodeIndex)
        ),
    })
}

function normalizeNotebookAIInsertedMarkdown(markdown: string): string {
    return markdown
        .replace(
            /(^|\n)<insight>\s*([A-Za-z0-9_-]+)\s*<\/insight>(?=\n|$)/gi,
            (_match, prefix: string, shortId: string) => `${prefix}${getSavedInsightQueryMarkdown(shortId)}`
        )
        .replace(
            /(^|\n)<Insight\s+(?:id|shortId)=["']([A-Za-z0-9_-]+)["']\s*\/>(?=\n|$)/g,
            (_match, prefix: string, shortId: string) => `${prefix}${getSavedInsightQueryMarkdown(shortId)}`
        )
}

function getSavedInsightQueryMarkdown(shortId: string): string {
    return `<Query query={{"kind":"SavedInsightNode","shortId":"${shortId}"}} />`
}

function stripEchoedNotebookContextBeforeAICursor(
    currentNodes: NotebookBlockNode[],
    cursorIndex: number,
    replacementNodes: NotebookBlockNode[]
): NotebookBlockNode[] {
    if (replacementNodes.length <= 1) {
        return replacementNodes
    }

    const cursorNode = currentNodes[cursorIndex]
    if (!cursorNode || isNotebookAgentNode(cursorNode)) {
        return replacementNodes
    }

    const prefixWithCursorNodes = currentNodes.slice(0, cursorIndex + 1).filter((node) => !isNotebookAgentNode(node))
    if (prefixWithCursorNodes.length && nodesStartWith(replacementNodes, prefixWithCursorNodes)) {
        return replacementNodes.slice(prefixWithCursorNodes.length)
    }

    const prefixNodes = currentNodes.slice(0, cursorIndex).filter((node) => !isNotebookAgentNode(node))
    if (!cursorNode || !prefixNodes.length || !nodesStartWith(replacementNodes, prefixNodes)) {
        return replacementNodes
    }

    const strippedTailNodes = stripNotebookAIAgentEchoFromTail(
        replacementNodes.slice(prefixNodes.length),
        prefixNodes,
        cursorNode
    )
    const tailNodes = replacementNodes.slice(prefixNodes.length)
    return nodesHaveSameFingerprints(strippedTailNodes, tailNodes) ? replacementNodes : strippedTailNodes
}

function stripNotebookAIAgentEchoFromTail(
    tailNodes: NotebookBlockNode[],
    prefixNodes: NotebookBlockNode[],
    cursorNode: NotebookBlockNode
): NotebookBlockNode[] {
    let nextNodes = tailNodes
    if (prefixNodes.length && nodesStartWith(nextNodes, prefixNodes)) {
        nextNodes = nextNodes.slice(prefixNodes.length)
    }

    if (nodesStartWith(nextNodes, [cursorNode])) {
        nextNodes = nextNodes.slice(1)
    }

    if (nodesEndWith(nextNodes, [cursorNode])) {
        nextNodes = nextNodes.slice(0, -1)
    }

    return nextNodes
}

function nodesStartWith(nodes: NotebookBlockNode[], prefixNodes: NotebookBlockNode[]): boolean {
    if (nodes.length < prefixNodes.length) {
        return false
    }

    return prefixNodes.every((node, index) => getNodeFingerprint(node) === getNodeFingerprint(nodes[index]))
}

function nodesEndWith(nodes: NotebookBlockNode[], suffixNodes: NotebookBlockNode[]): boolean {
    if (nodes.length < suffixNodes.length) {
        return false
    }

    const offset = nodes.length - suffixNodes.length
    return suffixNodes.every((node, index) => getNodeFingerprint(node) === getNodeFingerprint(nodes[offset + index]))
}

function nodesHaveSameFingerprints(leftNodes: NotebookBlockNode[], rightNodes: NotebookBlockNode[]): boolean {
    return (
        leftNodes.length === rightNodes.length &&
        leftNodes.every((node, index) => getNodeFingerprint(node) === getNodeFingerprint(rightNodes[index]))
    )
}

function getNotebookAIAgentReplaceRange(
    nodes: NotebookBlockNode[],
    cursorIndex: number,
    replacedNodeCount: number
): { insertionIndex: number; deleteCount: number } {
    if (isNotebookAgentNode(nodes[cursorIndex])) {
        return { insertionIndex: cursorIndex, deleteCount: 0 }
    }

    const deleteEndExclusive = cursorIndex + 1
    const requestedDeleteCount = Math.max(1, Math.floor(replacedNodeCount))
    const insertionIndex = Math.max(0, deleteEndExclusive - requestedDeleteCount)
    const deleteNodes = nodes.slice(insertionIndex, deleteEndExclusive)
    if (deleteNodes.some(isNotebookAgentNode)) {
        return { insertionIndex: cursorIndex, deleteCount: 1 }
    }

    return { insertionIndex, deleteCount: deleteNodes.length }
}

function getNotebookAIAgentTargetIndex(
    nodes: NotebookBlockNode[],
    preferredIndex: number | undefined,
    agentIndex: number
): number {
    if (
        preferredIndex !== undefined &&
        preferredIndex >= 0 &&
        preferredIndex < nodes.length &&
        !isNotebookAgentNode(nodes[preferredIndex])
    ) {
        return preferredIndex
    }

    for (let index = agentIndex - 1; index >= 0; index--) {
        if (!isNotebookAgentNode(nodes[index])) {
            return index
        }
    }
    return agentIndex
}

function updateNotebookAIAgentCursor(
    nodes: NotebookBlockNode[],
    cursor: MarkdownNotebookCaretPosition
): NotebookBlockNode[] {
    const cursorProp = getNotebookAgentCursorProp(cursor)
    return nodes.map((node) => {
        const agent = getNotebookAgentFromNode(node)
        if (!agent || agent.id !== NOTEBOOK_AI_AGENT_ID || node.type !== 'component') {
            return node
        }

        return {
            ...node,
            props: {
                ...node.props,
                name: NOTEBOOK_AI_AGENT_NAME,
                cursor: cursorProp,
            },
        }
    })
}

function getNotebookNodeEndCursor(
    node: NotebookBlockNode | undefined,
    nodeIndex: number
): MarkdownNotebookCaretPosition {
    if (isNotebookTextBlockNode(node)) {
        return { nodeIndex, offset: getInlineText(node.children).length }
    }

    if (node?.type === 'list' && node.items.length > 0) {
        const listItemIndex = node.items.length - 1
        return {
            nodeIndex,
            listItemIndex,
            offset: getInlineText(node.items[listItemIndex].children).length,
        }
    }

    return { nodeIndex }
}

function isNotebookTextBlockNode(node: NotebookBlockNode | undefined): node is NotebookTextBlockNode {
    return !!node && (node.type === 'paragraph' || node.type === 'heading' || node.type === 'blockquote')
}

function createNotebookAgentId(): string {
    return Math.random().toString(36).slice(2, 10)
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
