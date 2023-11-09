// Helpers for Kea issue with double importing
import { Editor as TTEditor, getText, TextSerializer } from '@tiptap/core'
import { NotebookNodeType } from '~/types'
import { JSONContent } from './types'

// Loosely based on https://github.com/ueberdosis/tiptap/blob/develop/packages/extension-floating-menu/src/floating-menu-plugin.ts#LL38C3-L55C4
export const isCurrentNodeEmpty = (editor: TTEditor): boolean => {
    const selection = editor.state.selection
    const { $anchor, empty } = selection
    const isEmptyTextBlock =
        $anchor.parent.isTextblock &&
        !$anchor.parent.type.spec.code &&
        $anchor.depth <= 1 &&
        !textContent($anchor.parent)

    if (empty && isEmptyTextBlock) {
        return true
    }

    return false
}

export const textContent = (node: any): string => {
    // we've extended the node schema to support a custom serializedText function
    // each custom node type needs to implement this function, or have an alternative in the map below
    const customOrTitleSerializer: TextSerializer = (props): string => {
        // TipTap chooses whether to add a separator based on a couple of factors
        // but, we always want a separator since this text is for search purposes
        const serializedText = props.node.type.spec.serializedText?.(props.node.attrs) || props.node.attrs?.title || ''
        if (serializedText.length > 0 && serializedText[serializedText.length - 1] !== '\n') {
            return serializedText + '\n'
        }
        return serializedText
    }

    // we want the type system to complain if we forget to add a custom serializer
    const customNodeTextSerializers: Record<NotebookNodeType, TextSerializer> = {
        'ph-backlink': customOrTitleSerializer,
        'ph-early-access-feature': customOrTitleSerializer,
        'ph-experiment': customOrTitleSerializer,
        'ph-feature-flag': customOrTitleSerializer,
        'ph-feature-flag-code-example': customOrTitleSerializer,
        'ph-image': customOrTitleSerializer,
        'ph-person': customOrTitleSerializer,
        'ph-query': customOrTitleSerializer,
        'ph-recording': customOrTitleSerializer,
        'ph-recording-playlist': customOrTitleSerializer,
        'ph-replay-timestamp': customOrTitleSerializer,
        'ph-survey': customOrTitleSerializer,
        'ph-group': customOrTitleSerializer,
        'ph-cohort': customOrTitleSerializer,
        'ph-person-feed': customOrTitleSerializer,
        'ph-properties': customOrTitleSerializer,
        'ph-map': customOrTitleSerializer,
        'ph-mention': customOrTitleSerializer,
    }

    return getText(node, {
        blockSeparator: '\n',
        textSerializers: customNodeTextSerializers,
    })
}

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

    return { type: 'doc', content: initialContent }
}
