// Helpers for Kea issue with double importing
import { LemonButtonProps } from '@posthog/lemon-ui'
import {
    ChainedCommands as EditorCommands,
    Editor as TTEditor,
    FocusPosition as EditorFocusPosition,
    getText,
    JSONContent as TTJSONContent,
    Range as EditorRange,
    TextSerializer,
} from '@tiptap/core'
import { Node as PMNode } from '@tiptap/pm/model'
import { NotebookNodeResource, NotebookNodeType } from '~/types'

export interface Node extends PMNode {}
export interface JSONContent extends TTJSONContent {}

export {
    ChainedCommands as EditorCommands,
    Range as EditorRange,
    FocusPosition as EditorFocusPosition,
} from '@tiptap/core'

export type CustomNotebookNodeAttributes = Record<string, any>

export type NotebookNodeAttributes<T extends CustomNotebookNodeAttributes> = T & {
    nodeId: string
    height?: string | number
    title?: string
    __init?: {
        expanded?: boolean
        showSettings?: boolean
    }
    // TODO: Type this more specifically to be our supported nodes only
    children?: NotebookNodeResource[]
}

// NOTE: Pushes users to use the parsed "attributes" instead
export type NotebookNode = Omit<PMNode, 'attrs'>

export type NotebookNodeAttributeProperties<T extends CustomNotebookNodeAttributes> = {
    attributes: NotebookNodeAttributes<T>
    updateAttributes: (attributes: Partial<NotebookNodeAttributes<T>>) => void
}

export type NotebookNodeProps<T extends CustomNotebookNodeAttributes> = NotebookNodeAttributeProperties<T>

export type NotebookNodeSettings =
    // using 'any' here shouldn't be necessary but, I couldn't figure out how to set a generic on the notebookNodeLogic props
    (({ attributes, updateAttributes }: NotebookNodeAttributeProperties<any>) => JSX.Element) | null

export type NotebookNodeAction = Pick<LemonButtonProps, 'icon'> & {
    text: string
    onClick: () => void
}

export interface NotebookEditor {
    getJSON: () => JSONContent
    getText: () => string
    getEndPosition: () => number
    getSelectedNode: () => Node | null
    getAdjacentNodes: (pos: number) => { previous: Node | null; next: Node | null }
    setEditable: (editable: boolean) => void
    setContent: (content: JSONContent) => void
    setSelection: (position: number) => void
    setTextSelection: (position: number | EditorRange) => void
    focus: (position: EditorFocusPosition) => void
    destroy: () => void
    deleteRange: (range: EditorRange) => EditorCommands
    insertContent: (content: JSONContent) => void
    insertContentAfterNode: (position: number, content: JSONContent) => void
    pasteContent: (position: number, text: string) => void
    findNode: (position: number) => Node | null
    findNodePositionByAttrs: (attrs: Record<string, any>) => any
    nextNode: (position: number) => { node: Node; position: number } | null
    hasChildOfType: (node: Node, type: string) => boolean
    scrollToSelection: () => void
    scrollToPosition: (position: number) => void
}

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
