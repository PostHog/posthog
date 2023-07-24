import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { NotebookNodeType } from '~/types'
import { sessionRecordingPlayerLogic } from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { dayjs } from 'lib/dayjs'
import { JSONContent } from '../Notebook/utils'
import { sessionRecordingPlayerProps } from './NotebookNodeRecording'
import clsx from 'clsx'
import { lastChildOfType } from '../Notebook/Editor'

const Component = (props: NodeViewProps): JSX.Element => {
    const playbackTime: number = props.node.attrs.playbackTime

    return (
        <NodeViewWrapper
            as="span"
            class={clsx('NotebookRecordingTimestamp', props.selected && 'NotebookRecordingTimestamp--selected')}
        >
            {formatTimestamp(playbackTime)}
        </NodeViewWrapper>
    )
}

function formatTimestamp(time: number): string {
    return dayjs.duration(time, 'milliseconds').format('HH:mm:ss').replace(/^00:/, '').trim()
}

export const NotebookNodeReplayTimestamp = Node.create({
    name: NotebookNodeType.ReplayTimestamp,
    inline: true,
    group: 'inline',
    atom: true,

    addAttributes() {
        return {
            playbackTime: { default: null, keepOnSplit: false },
            sessionRecordingId: { default: null, keepOnSplit: true, isRequired: true },
        }
    },

    parseHTML() {
        return [{ tag: NotebookNodeType.ReplayTimestamp }]
    },

    renderHTML({ HTMLAttributes }) {
        return [NotebookNodeType.ReplayTimestamp, mergeAttributes(HTMLAttributes)]
    },

    addKeyboardShortcuts() {
        return {
            Enter: ({ editor }) => {
                const selectedNode = editor.state.selection.$head.parent
                const timestampChild = lastChildOfType(selectedNode, NotebookNodeType.ReplayTimestamp)

                // TODO: There are more edge cases here from a UX perspective to be thought about...

                if (selectedNode.type.name === 'paragraph' && timestampChild) {
                    const sessionRecordingId = timestampChild.attrs.sessionRecordingId

                    const currentPlayerTime =
                        sessionRecordingPlayerLogic.findMounted(sessionRecordingPlayerProps(sessionRecordingId))?.values
                            .currentPlayerTime || 0

                    return editor.commands.insertContent(
                        buildTimestampCommentContent(currentPlayerTime, sessionRecordingId)
                    )
                }

                return false
            },
        }
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})

export function buildTimestampCommentContent(
    currentPlayerTime: number | null,
    sessionRecordingId: string
): JSONContent {
    return [
        {
            type: 'paragraph',
            content: [
                {
                    type: NotebookNodeType.ReplayTimestamp,
                    attrs: { playbackTime: currentPlayerTime, sessionRecordingId: sessionRecordingId },
                },
                { type: 'text', text: ' ' },
            ],
        },
    ]
}
