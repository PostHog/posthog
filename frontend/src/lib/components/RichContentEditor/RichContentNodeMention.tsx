import { Node, NodeViewProps, mergeAttributes } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import clsx from 'clsx'

import { RichContentMention } from './RichContentMention'
import { RichContentNodeType } from './types'

export interface RichContentNodeMentionAttrs {
    id?: number
}

const Component = (props: NodeViewProps): JSX.Element => {
    const { id } = props.node.attrs as RichContentNodeMentionAttrs

    return (
        <NodeViewWrapper
            as="span"
            className={clsx('RichContentEditorMention', props.selected && 'RichContentEditorMention--selected')}
        >
            <RichContentMention id={id} />
        </NodeViewWrapper>
    )
}

export const RichContentNodeMention = Node.create({
    name: RichContentNodeType.Mention,
    inline: true,
    group: 'inline',
    atom: true,

    serializedText: (attrs: RichContentNodeMentionAttrs): string => {
        // mention is not a block so `getText` does not add a separator.
        // we need to add it manually
        return `(member:${attrs.id})`
    },

    addAttributes() {
        return {
            id: { default: null },
        }
    },

    parseHTML() {
        return [{ tag: RichContentNodeType.Mention }]
    },

    renderHTML({ HTMLAttributes }) {
        return [RichContentNodeType.Mention, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
