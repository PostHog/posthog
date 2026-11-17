import { JSONContent } from 'lib/components/RichContentEditor/types'

import { buildMarkdownNotebookContent, convertNotebookContentToMarkdown } from './Notebook/markdownNotebookV2'
import { CreatePostHogWidgetNodeOptions } from './types'

export const KNOWN_NODES: Record<string, CreatePostHogWidgetNodeOptions<any>> = {}

export function defaultNotebookContent(title?: string, content?: JSONContent[]): JSONContent {
    const initialContent = [
        {
            type: 'heading',
            attrs: { level: 1 },
            content: [{ type: 'text', text: title }],
        },
    ] as JSONContent[]

    if (content) {
        initialContent.push(...content)
    }

    const richContent: JSONContent = { type: 'doc', content: initialContent }

    return buildMarkdownNotebookContent(convertNotebookContentToMarkdown(richContent))
}

export function updateContentHeading(content: JSONContent, newTitle: string): JSONContent {
    const firstNode = content?.content?.[0]
    const firstTextNode = firstNode?.content?.[0]
    if (!firstNode || !firstTextNode?.text) {
        return content
    }

    return {
        ...content,
        content: [
            {
                ...firstNode,
                content: [{ ...firstTextNode, text: newTitle }, ...(firstNode.content?.slice(1) ?? [])],
            },
            ...(content.content?.slice(1) ?? []),
        ],
    }
}
