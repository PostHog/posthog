// Helpers for Kea issue with double importing
import { LemonButtonProps } from '@posthog/lemon-ui'
import { Attribute, Editor as TTEditor, ExtendedRegExpMatchArray, getText, TextSerializer } from '@tiptap/core'

import { NotebookNodeResource, NotebookNodeType } from '~/types'

import type { NotebookNodeLogicProps } from '../Nodes/notebookNodeLogic'
import { JSONContent, RichContentEditorType, RichContentNode } from 'lib/components/RichContentEditor/types'

// TODO: fix the typing of string to NotebookNodeType
export const KNOWN_NODES: Record<string, CreatePostHogWidgetNodeOptions<any>> = {}

export type CreatePostHogWidgetNodeOptions<T extends CustomNotebookNodeAttributes> = Omit<
    NodeWrapperProps<T>,
    'updateAttributes'
> & {
    Component: (props: NotebookNodeProps<T>) => JSX.Element | null
    pasteOptions?: {
        find: string | RegExp
        getAttributes: (match: ExtendedRegExpMatchArray) => Promise<T | null | undefined> | T | null | undefined
    }
    attributes: Record<keyof T, Partial<Attribute>>
    serializedText?: (attributes: NotebookNodeAttributes<T>) => string
}

export type NodeWrapperProps<T extends CustomNotebookNodeAttributes> = Omit<NotebookNodeLogicProps, 'notebookLogic'> &
    NotebookNodeProps<T> & {
        Component: (props: NotebookNodeProps<T>) => JSX.Element | null

        // View only props
        href?: string | ((attributes: NotebookNodeAttributes<T>) => string | undefined)
        expandable?: boolean
        selected?: boolean
        heightEstimate?: number | string
        minHeight?: number | string
        /** If true the metadata area will only show when hovered if in editing mode */
        autoHideMetadata?: boolean
        /** Expand the node if the component is clicked */
        expandOnClick?: boolean
        settingsIcon?: JSX.Element | 'filter' | 'gear'
    }

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
export type NotebookNode = Omit<RichContentNode, 'attrs'>

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

export interface NotebookEditor extends RichContentEditorType {
    findCommentPosition: (markId: string) => number | null
    removeComment: (pos: number) => void
    getText: () => string
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
        [NotebookNodeType.Backlink]: customOrTitleSerializer,
        [NotebookNodeType.EarlyAccessFeature]: customOrTitleSerializer,
        [NotebookNodeType.Experiment]: customOrTitleSerializer,
        [NotebookNodeType.FeatureFlag]: customOrTitleSerializer,
        [NotebookNodeType.FeatureFlagCodeExample]: customOrTitleSerializer,
        [NotebookNodeType.Image]: customOrTitleSerializer,
        [NotebookNodeType.Person]: customOrTitleSerializer,
        [NotebookNodeType.Query]: customOrTitleSerializer,
        [NotebookNodeType.Recording]: customOrTitleSerializer,
        [NotebookNodeType.RecordingPlaylist]: customOrTitleSerializer,
        [NotebookNodeType.ReplayTimestamp]: customOrTitleSerializer,
        [NotebookNodeType.Survey]: customOrTitleSerializer,
        [NotebookNodeType.Group]: customOrTitleSerializer,
        [NotebookNodeType.Cohort]: customOrTitleSerializer,
        [NotebookNodeType.PersonFeed]: customOrTitleSerializer,
        [NotebookNodeType.Properties]: customOrTitleSerializer,
        [NotebookNodeType.Map]: customOrTitleSerializer,
        [NotebookNodeType.Mention]: customOrTitleSerializer,
        [NotebookNodeType.Embed]: customOrTitleSerializer,
        [NotebookNodeType.Latex]: customOrTitleSerializer,
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
