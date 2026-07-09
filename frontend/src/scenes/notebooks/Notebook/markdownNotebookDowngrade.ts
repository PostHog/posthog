/**
 * Downgrades a markdown (v2) notebook to TipTap JSONContent (v1) — the inverse of
 * `convertNotebookContentToMarkdown`.
 *
 * Known one-way losses (v1 has nowhere to store these):
 * - Discussion `<Comment ref="…" replies={…} />` threads: the inline `<ref>` highlight survives as
 *   a v1 `comment` mark (so the anchor is preserved), but the thread node and its replies are
 *   dropped — v1 keeps discussion threads outside the document content.
 * - `<Prompt />` blocks are dropped — v1 has no equivalent node.
 * - Authorial `<!-- … -->` comments become plain paragraphs: the note text stays visible, but its
 *   comment framing is lost.
 * - Table column alignments are dropped — v1 tables do not store alignment.
 * - Code block comment anchors (`ref=` tokens in the fence info string) are dropped — v1 code
 *   blocks carry no inline marks to anchor to.
 */
import {
    COMMENT_COMPONENT_TAG,
    DIVIDER_COMPONENT_TAG,
    isDiscussionCommentProps,
    parseMarkdownNotebook,
    serializeNode,
} from 'lib/components/MarkdownNotebook/markdown'
import {
    NotebookBlockNode,
    NotebookCodeBlockNode,
    NotebookComponentBlockNode,
    NotebookInlineMark,
    NotebookInlineNode,
    NotebookListBlockNode,
    NotebookTableBlockNode,
    NotebookTableCell,
} from 'lib/components/MarkdownNotebook/types'
import { JSONContent } from 'lib/components/RichContentEditor/types'

import { NotebookNodeType } from '../types'
import { NOTEBOOK_NODE_TYPE_TO_MARKDOWN_TAG } from './markdownNotebookV2'

type JSONContentMark = NonNullable<JSONContent['marks']>[number]

const MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE: Partial<Record<string, NotebookNodeType>> = Object.entries(
    NOTEBOOK_NODE_TYPE_TO_MARKDOWN_TAG
).reduce<Partial<Record<string, NotebookNodeType>>>((mapping, [nodeType, tagName]) => {
    if (tagName) {
        mapping[tagName] = nodeType as NotebookNodeType
    }
    return mapping
}, {})

// No v1 equivalent — dropped on downgrade (see module docstring).
const DROPPED_COMPONENT_TAGS = new Set(['Prompt'])

export function convertMarkdownToNotebookContent(markdown: string): JSONContent {
    const document = parseMarkdownNotebook(markdown)
    const content = document.nodes.flatMap((node) => {
        const converted = convertBlockNode(node)
        return converted ? [converted].flat() : []
    })

    return { type: 'doc', content }
}

function convertBlockNode(node: NotebookBlockNode): JSONContent | JSONContent[] | null {
    if (node.type === 'paragraph') {
        return makeParagraph(convertInlineNodes(node.children))
    }
    if (node.type === 'heading') {
        const content = convertInlineNodes(node.children)
        return { type: 'heading', attrs: { level: node.level ?? 1 }, ...(content.length ? { content } : {}) }
    }
    if (node.type === 'blockquote') {
        return { type: 'blockquote', content: [makeParagraph(convertInlineNodes(node.children))] }
    }
    if (node.type === 'list') {
        const lists = convertListNode(node)
        return node.blockquote ? { type: 'blockquote', content: lists } : lists
    }
    if (node.type === 'table') {
        return convertTableNode(node)
    }
    if (node.type === 'code') {
        return convertCodeNode(node)
    }
    if (node.type === 'component') {
        return convertComponentNode(node)
    }
    return makeParagraph(convertInlineNodes(node.children))
}

function convertComponentNode(node: NotebookComponentBlockNode): JSONContent | null {
    if (node.tagName === DIVIDER_COMPONENT_TAG) {
        return { type: 'horizontalRule' }
    }
    if (node.tagName === COMMENT_COMPONENT_TAG) {
        if (isDiscussionCommentProps(node.props)) {
            // Discussion thread: the inline `<ref>` highlight already became a `comment` mark on
            // the text it anchors to; the thread itself cannot be represented in v1 content, so it
            // is dropped (see module docstring).
            return null
        }
        // Authorial note: surfaced as a plain paragraph so the text stays visible in v1, even
        // though its comment framing is lost.
        const text = typeof node.props.text === 'string' ? node.props.text : ''
        return text ? makeParagraph(makeTextWithHardBreaks(text)) : null
    }
    if (DROPPED_COMPONENT_TAGS.has(node.tagName)) {
        return null
    }
    if (node.tagName === 'Image') {
        return {
            type: NotebookNodeType.Image,
            attrs: {
                src: typeof node.props.src === 'string' ? node.props.src : '',
                alt: typeof node.props.alt === 'string' ? node.props.alt : '',
            },
        }
    }
    if (node.tagName === 'UnknownNode') {
        // The upgrade path wraps unmapped v1 nodes as `<UnknownNode nodeType="…" … />` — re-emit
        // the original node so the downgrade restores it exactly.
        const { nodeType, ...attrs } = node.props
        if (typeof nodeType === 'string') {
            return { type: nodeType, attrs }
        }
    }

    const notebookNodeType = MARKDOWN_TAG_TO_NOTEBOOK_NODE_TYPE[node.tagName]
    if (notebookNodeType) {
        return { type: notebookNodeType, attrs: getNotebookNodeAttrsForMarkdownComponent(node) }
    }

    // No v1 node type for this tag — keep the serialized tag source as paragraph text so the
    // content is never silently lost.
    return makeParagraph(makeTextWithHardBreaks(serializeNode(node)))
}

function getNotebookNodeAttrsForMarkdownComponent(node: NotebookComponentBlockNode): JSONContent['attrs'] {
    if (typeof node.props.hideFilters === 'boolean' || typeof node.props.edit === 'boolean') {
        return { ...node.props }
    }
    return { ...node.props, edit: true }
}

function convertListNode(node: NotebookListBlockNode): JSONContent[] {
    // Inverse of `serializeList` in markdownNotebookV2.ts: items with greater depth nest into the
    // previous shallower item's listItem as a child list. taskList and bulletList items cannot
    // mix, so a task/plain change at the same depth splits into sibling lists — checked state is
    // never dropped.
    const rootLists: JSONContent[] = []
    const listStack: JSONContent[] = []
    const isTaskItem = (item: NotebookListBlockNode['items'][number]): boolean =>
        !(item.ordered ?? node.ordered) && item.checked !== undefined

    const attachList = (list: JSONContent): void => {
        const parentItems = listStack[listStack.length - 1]?.content
        const parentItem = parentItems?.[parentItems.length - 1]
        if (parentItem) {
            parentItem.content = [...(parentItem.content ?? []), list]
        } else {
            rootLists.push(list)
        }
        listStack.push(list)
    }

    for (const item of node.items) {
        const task = isTaskItem(item)
        const depth = Math.max(0, item.depth)
        while (listStack.length - 1 > depth) {
            listStack.pop()
        }
        if (!listStack.length) {
            attachList(makeList(node.ordered, node.start, task))
        }
        while (listStack.length - 1 < depth) {
            if (!(listStack[listStack.length - 1].content ?? []).length) {
                // Nothing to nest under — keep the item at the current depth.
                break
            }
            attachList(makeList(item.ordered ?? node.ordered, item.start, task))
        }
        if ((listStack[listStack.length - 1].type === 'taskList') !== task) {
            listStack.pop()
            attachList(makeList(item.ordered ?? node.ordered, item.start, task))
        }
        const currentList = listStack[listStack.length - 1]
        const itemNode: JSONContent = task
            ? { type: 'taskItem', attrs: { checked: item.checked ?? false } }
            : { type: 'listItem' }
        currentList.content = [
            ...(currentList.content ?? []),
            { ...itemNode, content: [makeParagraph(convertInlineNodes(item.children))] },
        ]
    }

    return rootLists
}

function makeList(ordered: boolean, start: number | undefined, task: boolean): JSONContent {
    if (!ordered && task) {
        return { type: 'taskList', content: [] }
    }
    return {
        type: ordered ? 'orderedList' : 'bulletList',
        ...(ordered && start !== undefined && start !== 1 ? { attrs: { start } } : {}),
        content: [],
    }
}

function convertTableNode(node: NotebookTableBlockNode): JSONContent {
    // `node.alignments` is dropped — v1 tables do not store column alignment.
    const headerRow: JSONContent = {
        type: 'tableRow',
        content: node.headers.map((cell) => makeTableCellNode('tableHeader', cell)),
    }
    const bodyRows = node.rows.map(
        (row): JSONContent => ({
            type: 'tableRow',
            content: row.map((cell) => makeTableCellNode('tableCell', cell)),
        })
    )

    return { type: 'table', content: [headerRow, ...bodyRows] }
}

function makeTableCellNode(type: 'tableHeader' | 'tableCell', cell: NotebookTableCell): JSONContent {
    return { type, content: [makeParagraph(convertInlineNodes(cell.children))] }
}

function convertCodeNode(node: NotebookCodeBlockNode): JSONContent {
    return {
        type: 'codeBlock',
        attrs: { language: node.language ?? null },
        // v1 code blocks hold plain text; one text node with embedded newlines round-trips through
        // the upgrade path, which joins child text and hardBreaks back into the code string.
        ...(node.text ? { content: [{ type: 'text', text: node.text }] } : {}),
    }
}

function convertInlineNodes(nodes: NotebookInlineNode[]): JSONContent[] {
    const content: JSONContent[] = []
    for (const node of nodes) {
        const converted = convertInlineNode(node)
        const previous = content[content.length - 1]
        if (
            converted.type === NotebookNodeType.Mention &&
            previous?.type === NotebookNodeType.Mention &&
            previous.attrs?.id === converted.attrs?.id
        ) {
            // One labeled mention can parse into several adjacent runs (e.g. a partially bold
            // label); they all collapse into the same atomic v1 mention.
            continue
        }
        content.push(converted)
    }
    return content
}

function convertInlineNode(node: NotebookInlineNode): JSONContent {
    if (node.type === 'hardBreak') {
        return { type: 'hardBreak' }
    }

    const mentionMark = (node.marks ?? []).find(
        (mark): mark is Extract<NotebookInlineMark, { type: 'mention' }> => mark.type === 'mention'
    )
    if (mentionMark) {
        const memberId = Number(mentionMark.id)
        if (Number.isFinite(memberId)) {
            // v1 mentions are atomic nodes whose label is derived from the member id at render
            // time, so the mention replaces the labeled text.
            return { type: NotebookNodeType.Mention, attrs: { id: memberId } }
        }
    }

    const marks = convertInlineMarks(node.marks ?? [])
    return { type: 'text', text: node.text, ...(marks.length ? { marks } : {}) }
}

function convertInlineMarks(marks: NotebookInlineMark[]): JSONContentMark[] {
    return marks.flatMap((mark): JSONContentMark[] => {
        if (
            mark.type === 'bold' ||
            mark.type === 'italic' ||
            mark.type === 'underline' ||
            mark.type === 'strike' ||
            mark.type === 'code'
        ) {
            return [{ type: mark.type }]
        }
        if (mark.type === 'link') {
            return [{ type: 'link', attrs: { href: mark.href } }]
        }
        if (mark.type === 'ref') {
            return [{ type: 'comment', attrs: { id: mark.id } }]
        }
        // 'mention' is handled as an atomic node in convertInlineNode; a mention with a
        // non-numeric id degrades to its plain-text label.
        return []
    })
}

function makeParagraph(content: JSONContent[]): JSONContent {
    return { type: 'paragraph', ...(content.length ? { content } : {}) }
}

function makeTextWithHardBreaks(text: string): JSONContent[] {
    const content: JSONContent[] = []
    text.split('\n').forEach((line, index) => {
        if (index > 0) {
            content.push({ type: 'hardBreak' })
        }
        if (line) {
            content.push({ type: 'text', text: line })
        }
    })
    return content
}
