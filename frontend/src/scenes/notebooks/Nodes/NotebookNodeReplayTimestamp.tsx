import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { NotebookNodeType, NotebookTarget } from '~/types'
import {
    sessionRecordingPlayerLogic,
    SessionRecordingPlayerLogicProps,
} from 'scenes/session-recordings/player/sessionRecordingPlayerLogic'
import { dayjs } from 'lib/dayjs'
import { JSONContent } from '../Notebook/utils'
import clsx from 'clsx'
import { findPositionOfClosestNodeMatchingAttrs } from '../Notebook/Editor'
import { urls } from 'scenes/urls'
import { Link } from '@posthog/lemon-ui'
import { openNotebook } from '../Notebook/notebooksListLogic'
import { notebookLogic } from '../Notebook/notebookLogic'
import { useValues } from 'kea'

const Component = (props: NodeViewProps): JSX.Element => {
    const { shortId } = useValues(notebookLogic)
    const sessionRecordingId: string = props.node.attrs.sessionRecordingId
    const playbackTime: number = props.node.attrs.playbackTime
    const logicProps: SessionRecordingPlayerLogicProps = sessionRecordingPlayerProps(sessionRecordingId)

    const recordingNodePosition = findPositionOfClosestNodeMatchingAttrs(props.editor, props.getPos(), {
        id: sessionRecordingId,
    })

    const handleOnClick = (): void => {
        const logic = sessionRecordingPlayerLogic.findMounted(logicProps)

        if (logic) {
            logic.actions.seekToTime(props.node.attrs.playbackTime)
            logic.actions.setPlay()
            if (recordingNodePosition) {
                const domEl = props.editor.view.nodeDOM(recordingNodePosition) as HTMLElement
                domEl.scrollIntoView()
            }
        } else {
            openNotebook(shortId, NotebookTarget.Sidebar)
        }
    }

    return (
        <NodeViewWrapper
            as="span"
            class={clsx('NotebookRecordingTimestamp', props.selected && 'NotebookRecordingTimestamp--selected')}
        >
            <Link
                to={
                    !!recordingNodePosition
                        ? undefined
                        : urls.replaySingle(sessionRecordingId) + `?t=${playbackTime / 1000}`
                }
                onClick={handleOnClick}
            >
                {formatTimestamp(playbackTime)}
            </Link>
        </NodeViewWrapper>
    )
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

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})

export function formatTimestamp(time: number): string {
    return dayjs.duration(time, 'milliseconds').format('HH:mm:ss').replace(/^00:/, '').trim()
}

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
