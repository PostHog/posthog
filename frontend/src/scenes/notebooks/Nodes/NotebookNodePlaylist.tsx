import { mergeAttributes, Node, nodePasteRule, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from 'scenes/notebooks/Nodes/types'
import {
    RecordingsLists,
    SessionRecordingsPlaylistProps,
} from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { createUrlRegex, useJsonNodeState } from './utils'
import { sessionRecordingsListLogic } from 'scenes/session-recordings/playlist/sessionRecordingsListLogic'
import { useActions, useValues } from 'kea'
import { SessionRecordingPlayer } from 'scenes/session-recordings/player/SessionRecordingPlayer'
import { useRef } from 'react'
import { fromParamsGivenUrl, uuid } from 'lib/utils'
import { LemonButton } from '@posthog/lemon-ui'
import { IconChevronLeft } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

const Component = (props: NodeViewProps): JSX.Element => {
    const [filters, setFilters] = useJsonNodeState(props, 'filters')

    const playerKey = useRef(`notebook-${uuid()}`).current

    const recordingPlaylistLogicProps: SessionRecordingsPlaylistProps = {
        filters,
        updateSearchParams: false,
        autoPlay: false,
        mode: 'notebook',
        onFiltersChange: setFilters,
    }

    const logic = sessionRecordingsListLogic(recordingPlaylistLogicProps)
    const { activeSessionRecording, nextSessionRecording } = useValues(logic)
    const { setSelectedRecordingId } = useActions(logic)

    const content = !activeSessionRecording?.id ? (
        <RecordingsLists {...recordingPlaylistLogicProps} />
    ) : (
        <>
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconChevronLeft />}
                onClick={() => setSelectedRecordingId(null)}
                className="self-start"
            />
            <SessionRecordingPlayer
                playerKey={playerKey}
                sessionRecordingId={activeSessionRecording.id}
                matching={activeSessionRecording?.matching_events}
                recordingStartTime={activeSessionRecording ? activeSessionRecording.start_time : undefined}
                nextSessionRecording={nextSessionRecording}
            />
        </>
    )

    return (
        <NodeWrapper
            {...props}
            className={NotebookNodeType.RecordingPlaylist}
            title="Playlist"
            href={urls.sessionRecordings(undefined, filters)}
        >
            <div className="flex flex-row overflow-hidden gap-2 flex-1" style={{ height: 600 }} contentEditable={false}>
                {content}
            </div>
        </NodeWrapper>
    )
}

export const NotebookNodePlaylist = Node.create({
    name: NotebookNodeType.RecordingPlaylist,
    group: 'block',
    atom: true,
    draggable: true,

    addAttributes() {
        return {
            filters: {
                default: {},
            },
        }
    },

    parseHTML() {
        return [
            {
                tag: NotebookNodeType.RecordingPlaylist,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [NotebookNodeType.RecordingPlaylist, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },

    addPasteRules() {
        return [
            nodePasteRule({
                find: createUrlRegex(urls.sessionRecordings() + '(.+)'),
                type: this.type,
                getAttributes: (match) => {
                    const searchParams = fromParamsGivenUrl(match[1].split('?')[1] || '')

                    return { filters: searchParams.filters }
                },
            }),
        ]
    },
})
