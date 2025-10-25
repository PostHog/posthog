import { Node, NodeViewProps, mergeAttributes } from '@tiptap/core'
import { NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import clsx from 'clsx'
import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { urls } from 'scenes/urls'

import { openNotebook } from '~/models/notebooksModel'

import { notebookLogic } from '../Notebook/notebookLogic'
import { NotebookNodeType, NotebookTarget } from '../types'

export interface NotebookNodeReplayTimestampAttrs {
    playbackTime?: number
    sessionRecordingId: string
    sourceNodeId?: string
}

const Component = (props: NodeViewProps): JSX.Element => {
    const { shortId, findNodeLogic, findNodeLogicById } = useValues(notebookLogic)
    const { sessionRecordingId, playbackTime = 0, sourceNodeId } = props.node.attrs as NotebookNodeReplayTimestampAttrs

    const relatedNodeInNotebook = useMemo(() => {
        const logicById = sourceNodeId ? findNodeLogicById(sourceNodeId) : null

        return logicById ?? findNodeLogic(NotebookNodeType.Recording, { id: sessionRecordingId })
        // oxlint-disable-next-line exhaustive-deps
    }, [findNodeLogic])

    const handlePlayInNotebook = (): void => {
        // TODO: Figure out how to send this action info to the playlist OR the replay node...

        relatedNodeInNotebook?.values.sendMessage('play-replay', {
            sessionRecordingId,
            time: playbackTime ?? 0,
        })
    }

    return (
        <NodeViewWrapper
            as="span"
            className={clsx('NotebookRecordingTimestamp', props.selected && 'NotebookRecordingTimestamp--selected')}
        >
            <LemonButton
                size="small"
                noPadding
                active
                onClick={
                    relatedNodeInNotebook ? handlePlayInNotebook : () => openNotebook(shortId, NotebookTarget.Popover)
                }
                to={
                    !relatedNodeInNotebook
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

    serializedText: (attrs: NotebookNodeReplayTimestampAttrs): string => {
        // timestamp is not a block so `getText` does not add a separator.
        // we need to add it manually
        return `${attrs.playbackTime ? formatTimestamp(attrs.playbackTime) : '00:00'}:\n`
    },

    addAttributes() {
        return {
            playbackTime: { default: null, keepOnSplit: false },
            sessionRecordingId: { default: null, keepOnSplit: true, isRequired: true },
            sourceNodeId: { default: null, keepOnSplit: true },
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
