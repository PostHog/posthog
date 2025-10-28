// Helpers for Kea issue with double importing
import { TextSerializer, getText } from '@tiptap/core'

import { JSONContent, RichContentNode, TTEditor } from 'lib/components/RichContentEditor/types'

import { CreatePostHogWidgetNodeOptions, NotebookNodeType } from './types'

export const KNOWN_NODES: Record<string, CreatePostHogWidgetNodeOptions<any>> = {}

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

export const textContent = (node: RichContentNode): string => {
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
        [NotebookNodeType.LLMTrace]: customOrTitleSerializer,
        [NotebookNodeType.Issues]: customOrTitleSerializer,
        [NotebookNodeType.RecordingPlaylist]: customOrTitleSerializer,
        [NotebookNodeType.ReplayTimestamp]: customOrTitleSerializer,
        [NotebookNodeType.Survey]: customOrTitleSerializer,
        [NotebookNodeType.Group]: customOrTitleSerializer,
        [NotebookNodeType.Cohort]: customOrTitleSerializer,
        [NotebookNodeType.PersonFeed]: customOrTitleSerializer,
        [NotebookNodeType.PersonProperties]: customOrTitleSerializer,
        [NotebookNodeType.GroupProperties]: customOrTitleSerializer,
        [NotebookNodeType.Map]: customOrTitleSerializer,
        [NotebookNodeType.Mention]: customOrTitleSerializer,
        [NotebookNodeType.Embed]: customOrTitleSerializer,
        [NotebookNodeType.Latex]: customOrTitleSerializer,
        [NotebookNodeType.TaskCreate]: customOrTitleSerializer,
        [NotebookNodeType.UsageMetrics]: customOrTitleSerializer,
        [NotebookNodeType.ZendeskTickets]: customOrTitleSerializer,
        [NotebookNodeType.RelatedGroups]: customOrTitleSerializer,
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
