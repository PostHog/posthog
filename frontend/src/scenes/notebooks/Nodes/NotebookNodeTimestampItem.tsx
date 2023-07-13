import {
    Node,
    NodeViewContent,
    NodeViewProps,
    NodeViewWrapper,
    ReactNodeViewRenderer,
    mergeAttributes,
    wrappingInputRule,
} from '@tiptap/react'
import { dayjs } from 'lib/dayjs'
import { useValues } from 'kea'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { NotebookNodeType } from '~/types'

const Component = (props: NodeViewProps): JSX.Element => {
    const timestamp = props.node.attrs.timestamp

    const id = 'TODO: get recording id from parent node'
    const recordingLogicProps: SessionRecordingPlayerLogicProps = {
        sessionRecordingId: id,
        playerKey: `notebook-${id}`,
    }

    const { currentTimestamp } = useValues(sessionRecordingPlayerLogic(recordingLogicProps))

    // const resetTimestamp = (): void => {
    //     props.updateAttributes({ timestamp: null })
    // }

    // const setTimestamp = (): void => {
    //     props.updateAttributes({ timestamp: currentTimestamp })
    // }

    return (
        <NodeViewWrapper>
            <li data-type={props.node.type.name} className="flex space-x-2">
                <span>{formatTimestamp(timestamp || currentTimestamp)}</span>
                <NodeViewContent />
            </li>
        </NodeViewWrapper>
    )
}

function formatTimestamp(timestamp: number | undefined): string {
    return dayjs
        .duration(timestamp || 0, 'milliseconds')
        .format('HH:mm:ss')
        .replace(/^00:/, '')
        .trim()
}

export const NotebookNodeTimestampItem = Node.create({
    name: NotebookNodeType.TimestampItem,
    content: 'paragraph+',
    defining: true,

    addAttributes() {
        return {
            timestamp: { default: null, keepOnSplit: false },
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
            Enter: () => this.editor.commands.splitListItem(this.name),
        }
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },

    addInputRules() {
        return [
            wrappingInputRule({
                find: /^\s*(\[([( |x])?\])\s$/,
                type: this.type,
            }),
        ]
    },
})
