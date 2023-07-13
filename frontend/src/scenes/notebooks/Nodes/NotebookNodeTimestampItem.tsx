import {
    Node,
    NodeViewContent,
    NodeViewProps,
    NodeViewWrapper,
    ReactNodeViewRenderer,
    mergeAttributes,
} from '@tiptap/react'
import { dayjs } from 'lib/dayjs'
import { useValues } from 'kea'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { NotebookNodeType } from '~/types'
import { hasContent } from '../Notebook/utils'
import clsx from 'clsx'

const Component = (props: NodeViewProps): JSX.Element => {
    const playbackTime = props.node.attrs.playbackTime
    const sessionRecordingId = props.node.attrs.sessionRecordingId

    const recordingLogicProps: SessionRecordingPlayerLogicProps = {
        sessionRecordingId,
        playerKey: `notebook-${sessionRecordingId}`,
    }

    const { currentPlayerTime } = useValues(sessionRecordingPlayerLogic(recordingLogicProps))

    const isEmpty = !hasContent(props.node)

    if (!isEmpty && !playbackTime) {
        setTimeout(() => {
            props.updateAttributes({ playbackTime: currentPlayerTime })
        }, 100)
    } else if (isEmpty && playbackTime) {
        setTimeout(() => {
            props.updateAttributes({ playbackTime: null })
        }, 100)
    }

    return (
        <NodeViewWrapper>
            <li data-type={props.node.type.name} className={clsx('flex space-x-2', isEmpty && 'empty')}>
                <span className="text-muted" contentEditable={false}>
                    {formatTimestamp(playbackTime || currentPlayerTime)}
                </span>
                <NodeViewContent />
            </li>
        </NodeViewWrapper>
    )
}

function formatTimestamp(time: number): string {
    return dayjs.duration(time, 'milliseconds').format('HH:mm:ss').replace(/^00:/, '').trim()
}

export const NotebookNodeTimestampItem = Node.create({
    name: NotebookNodeType.TimestampItem,
    content: 'paragraph+',
    defining: true,

    addAttributes() {
        return {
            playbackTime: { default: null, keepOnSplit: false },
            sessionRecordingId: { default: null, keepOnSplit: true, isRequired: true },
        }
    },

    parseHTML() {
        return [{ tag: `li[data-type="${this.name}"]`, priority: 51 }]
    },

    renderHTML({ HTMLAttributes }) {
        return ['li', mergeAttributes(HTMLAttributes, { 'data-type': this.name }), 0]
    },

    addKeyboardShortcuts() {
        return {
            Enter: ({ editor }) => {
                if (hasContent(editor.view.state.selection.$head.parent)) {
                    return this.editor.commands.splitListItem(this.name)
                } else {
                    return false
                }
            },
        }
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
