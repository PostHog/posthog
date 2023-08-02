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
import { sessionRecordingPlayerProps } from './NotebookNodeRecording'
import { useMemo } from 'react'

const Component = (props: NodeViewProps): JSX.Element => {
    const { shortId, findNodeLogic } = useValues(notebookLogic)
    const sessionRecordingId: string = props.node.attrs.sessionRecordingId
    const playbackTime: number = props.node.attrs.playbackTime

    const recordingNodeInNotebook = useMemo(() => {
        return findNodeLogic(NotebookNodeType.Recording, { id: sessionRecordingId })
    }, [findNodeLogic])

    const handlePlayInNotebook = (): void => {
        recordingNodeInNotebook?.actions.setExpanded(true)

        // TODO: Move all of the above into the logic / Node context for the recording node
        const logicProps: SessionRecordingPlayerLogicProps = sessionRecordingPlayerProps(sessionRecordingId)
        const logic = sessionRecordingPlayerLogic(logicProps)

        logic.actions.seekToTime(props.node.attrs.playbackTime)
        logic.actions.setPlay()

        const recordingNodePosition = findPositionOfClosestNodeMatchingAttrs(props.editor, props.getPos(), {
            id: sessionRecordingId,
        })

        const domEl = props.editor.view.nodeDOM(recordingNodePosition) as HTMLElement
        domEl.scrollIntoView()
    }

    return (
        <NodeViewWrapper
            as="span"
            className={clsx('NotebookRecordingTimestamp', props.selected && 'NotebookRecordingTimestamp--selected')}
        >
            {recordingNodeInNotebook ? (
                <span onClick={handlePlayInNotebook}>{formatTimestamp(playbackTime)}</span>
            ) : (
                <Link
                    to={urls.replaySingle(sessionRecordingId) + `?t=${playbackTime / 1000}`}
                    onClick={() => openNotebook(shortId, NotebookTarget.Sidebar)}
                >
                    {formatTimestamp(playbackTime)}
                </Link>
            )}
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
