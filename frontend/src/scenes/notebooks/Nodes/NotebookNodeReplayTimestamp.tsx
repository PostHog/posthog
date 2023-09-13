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
import { LemonButton } from '@posthog/lemon-ui'
import { notebookLogic } from '../Notebook/notebookLogic'
import { useValues } from 'kea'
import { sessionRecordingPlayerProps } from './NotebookNodeRecording'
import { useMemo } from 'react'
import { openNotebook } from '~/models/notebooksModel'

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
            <LemonButton
                size="small"
                noPadding
                type="secondary"
                status="primary-alt"
                onClick={
                    recordingNodeInNotebook ? handlePlayInNotebook : () => openNotebook(shortId, NotebookTarget.Popover)
                }
                to={
                    !recordingNodeInNotebook
                        ? urls.replaySingle(sessionRecordingId) + `?t=${playbackTime / 1000}`
                        : undefined
                }
            >
                <span className="p-1">{formatTimestamp(playbackTime)}</span>
            </LemonButton>
        </NodeViewWrapper>
    )
}

export const NotebookNodeReplayTimestamp = Node.create({
    name: NotebookNodeType.ReplayTimestamp,
    inline: true,
    group: 'inline',
    atom: true,

    serializedText:
        () =>
        (attrs: NotebookNodeReplayTimestampAttrs): string => {
            // timestamp is not a block so `getText` does not add a separator.
            // we need to add it manually
            return `${attrs.playbackTime ? formatTimestamp(attrs.playbackTime) : '00:00'}:\n`
        },

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

export interface NotebookNodeReplayTimestampAttrs {
    playbackTime: number | null
    sessionRecordingId: string
}

export function buildTimestampCommentContent(
    currentPlayerTime: number | null,
    sessionRecordingId: string
): JSONContent {
    return {
        type: 'paragraph',
        content: [
            {
                type: NotebookNodeType.ReplayTimestamp,
                attrs: { playbackTime: currentPlayerTime, sessionRecordingId: sessionRecordingId },
            },
            { type: 'text', text: ' ' },
        ],
    }
}
