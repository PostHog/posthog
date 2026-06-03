import { Node } from '@tiptap/core'
import { Link } from '@tiptap/extension-link'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table'
import { MarkdownManager } from '@tiptap/markdown'
import StarterKit from '@tiptap/starter-kit'

import { JSONContent } from 'lib/components/RichContentEditor/types'

import { NotebookNodeType } from './types'

type JsonRecord = Record<string, any>

const RESOURCE_NODE_TAGS: Partial<Record<NotebookNodeType, string>> = {
    [NotebookNodeType.FeatureFlag]: 'FeatureFlag',
    [NotebookNodeType.Experiment]: 'Experiment',
    [NotebookNodeType.Survey]: 'Survey',
    [NotebookNodeType.Cohort]: 'Cohort',
    [NotebookNodeType.Person]: 'Person',
    [NotebookNodeType.Group]: 'Group',
    [NotebookNodeType.Recording]: 'SessionReplay',
}

const EXECUTABLE_NODE_TAGS: Partial<Record<NotebookNodeType, string>> = {
    [NotebookNodeType.Python]: 'Python',
    [NotebookNodeType.HogQLSQL]: 'HogQL',
    [NotebookNodeType.DuckSQL]: 'DuckSQL',
}

function escapeHtmlAttribute(value: unknown): string {
    return String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
}

function titleAttribute(attrs: JsonRecord): string {
    return attrs.title ? ` title="${escapeHtmlAttribute(attrs.title)}"` : ''
}

function serializeIdAttribute(attrs: JsonRecord): string {
    return attrs.id !== null && attrs.id !== undefined ? ` id="${escapeHtmlAttribute(attrs.id)}"` : ''
}

export function notebookNodeToMarkdown(nodeType: string, attrs: JsonRecord | null | undefined): string {
    const safeAttrs = attrs || {}

    if (nodeType === NotebookNodeType.Query) {
        return `<Query${titleAttribute(safeAttrs)}>\n${JSON.stringify(safeAttrs.query || {}, null, 2)}\n</Query>`
    }

    if (
        nodeType === NotebookNodeType.Python ||
        nodeType === NotebookNodeType.HogQLSQL ||
        nodeType === NotebookNodeType.DuckSQL
    ) {
        const tag = EXECUTABLE_NODE_TAGS[nodeType]
        const returnVariable =
            nodeType !== NotebookNodeType.Python && safeAttrs.returnVariable
                ? ` return_variable="${escapeHtmlAttribute(safeAttrs.returnVariable)}"`
                : ''
        return `<${tag}${titleAttribute(safeAttrs)}${returnVariable}>\n${safeAttrs.code || ''}\n</${tag}>`
    }

    const resourceTag = RESOURCE_NODE_TAGS[nodeType as NotebookNodeType]
    if (resourceTag) {
        return `<${resourceTag}${serializeIdAttribute(safeAttrs)} />`
    }

    if (nodeType.startsWith('ph-')) {
        return `<NotebookNode type="${escapeHtmlAttribute(nodeType)}">\n${JSON.stringify(safeAttrs, null, 2)}\n</NotebookNode>`
    }

    return ''
}

const notebookMarkdownExtensions = Object.values(NotebookNodeType)
    .filter((nodeType) => nodeType.startsWith('ph-'))
    .map((nodeType) =>
        Node.create({
            name: nodeType,
            serializedText: () => '',
            renderMarkdown(node) {
                return notebookNodeToMarkdown(nodeType, node.attrs)
            },
        })
    )

const notebookMarkdownManager = new MarkdownManager({
    extensions: [
        StarterKit.configure({ link: false }),
        Link,
        Table,
        TableRow,
        TableHeader,
        TableCell,
        TaskList,
        TaskItem.configure({ nested: true }),
        ...notebookMarkdownExtensions,
    ],
})

export function notebookContentToMarkdown(content: JSONContent | JSONContent[] | null | undefined): string {
    if (!content) {
        return ''
    }

    return notebookMarkdownManager.serialize(Array.isArray(content) ? { type: 'doc', content } : content).trim()
}
