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

function serializeText(text: string): string {
    return text
        .replace(/\\/g, '\\\\')
        .replace(/\*/g, '\\*')
        .replace(/_/g, '\\_')
        .replace(/`/g, '\\`')
        .replace(/\[/g, '\\[')
        .replace(/\]/g, '\\]')
}

function serializeTextNode(node: JSONContent): string {
    let text = serializeText(node.text || '')
    for (const mark of node.marks || []) {
        if (mark.type === 'bold') {
            text = `**${text}**`
        } else if (mark.type === 'italic') {
            text = `*${text}*`
        } else if (mark.type === 'code') {
            text = `\`${node.text || ''}\``
        } else if (mark.type === 'link') {
            text = `[${text}](${mark.attrs?.href || ''})`
        }
    }
    return text
}

function inlineContentToMarkdown(node: JSONContent): string {
    return (node.content || [])
        .map((child) => (child.type === 'text' ? serializeTextNode(child) : nodeToMarkdown(child)))
        .join('')
}

function listItemText(item: JSONContent): string {
    return (item.content || [])
        .map((child) => {
            if (child.type === 'paragraph') {
                return inlineContentToMarkdown(child)
            }
            return nodeToMarkdown(child)
        })
        .filter(Boolean)
        .join('\n')
}

function codeBlockToMarkdown(node: JSONContent): string {
    const language = node.attrs?.language || ''
    const code = (node.content || []).map((child) => child.text || '').join('')
    return `\`\`\`${language}\n${code}\n\`\`\``
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

function nodeToMarkdown(node: JSONContent): string {
    const nodeType = node.type || ''
    const attrs = node.attrs || {}

    if (nodeType === 'heading') {
        const level = Math.max(1, Math.min(Number(attrs.level || 1), 6))
        return `${'#'.repeat(level)} ${inlineContentToMarkdown(node)}`
    }

    if (nodeType === 'paragraph') {
        return inlineContentToMarkdown(node)
    }

    if (nodeType === 'bulletList') {
        return (node.content || []).map((item) => `- ${listItemText(item)}`).join('\n')
    }

    if (nodeType === 'orderedList') {
        return (node.content || []).map((item, index) => `${index + 1}. ${listItemText(item)}`).join('\n')
    }

    if (nodeType === 'codeBlock') {
        return codeBlockToMarkdown(node)
    }

    if (nodeType === 'blockquote') {
        return (node.content || [])
            .map((child) =>
                nodeToMarkdown(child)
                    .split('\n')
                    .map((line) => `> ${line}`)
                    .join('\n')
            )
            .join('\n')
    }

    if (nodeType === 'horizontalRule') {
        return '---'
    }

    if (nodeType.startsWith('ph-')) {
        return notebookNodeToMarkdown(nodeType, attrs)
    }

    return (node.content || []).map(nodeToMarkdown).filter(Boolean).join('\n\n')
}

export function notebookContentToMarkdown(content: JSONContent | JSONContent[] | null | undefined): string {
    const nodes = Array.isArray(content) ? content : content?.content || []
    return nodes.map(nodeToMarkdown).filter(Boolean).join('\n\n').trim()
}
