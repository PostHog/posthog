import { Node, NodeViewProps, mergeAttributes } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import clsx from 'clsx'

import { RichContentMention } from './RichContentMention'
import { RichContentRoleMention } from './RichContentRoleMention'
import { RichContentNodeType } from './types'

export type RichContentMentionKind = 'member' | 'role'

export interface RichContentNodeMentionAttrs {
    /** A user id for a member mention, a role uuid for a role mention. */
    id?: number | string
    kind?: RichContentMentionKind
}

const Component = (props: NodeViewProps): JSX.Element => {
    const { id, kind } = props.node.attrs as RichContentNodeMentionAttrs

    return (
        <NodeViewWrapper
            as="span"
            className={clsx('RichContentEditorMention', props.selected && 'RichContentEditorMention--selected')}
        >
            {kind === 'role' ? <RichContentRoleMention id={String(id)} /> : <RichContentMention id={Number(id)} />}
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
        return `(${attrs.kind ?? 'member'}:${attrs.id})`
    },

    addAttributes() {
        return {
            id: { default: null },
            kind: { default: 'member' },
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
