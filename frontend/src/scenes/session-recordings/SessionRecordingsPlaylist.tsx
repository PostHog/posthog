import React from 'react'
import { useActions, useValues } from 'kea'
import { colonDelimitedDuration } from '~/lib/utils'
import { SessionRecordingType } from '~/types'
import { Button, Row } from 'antd'
import { sessionRecordingsTableLogic } from './sessionRecordingsTableLogic'
import { LeftOutlined, RightOutlined } from '@ant-design/icons'
import { asDisplay } from 'scenes/persons/PersonHeader'
import { RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import './SessionRecordingPlaylist.scss'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { TZLabel } from 'lib/components/TimezoneAware'
import { SessionRecordingPlayerV3 } from './player/SessionRecordingPlayer'
import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { Spinner } from 'lib/components/Spinner/Spinner'

interface SessionRecordingsTableProps {
    personUUID?: string
    isPersonPage?: boolean
}

export function SessionRecordingsPlaylist({ personUUID }: SessionRecordingsTableProps): JSX.Element {
    const sessionRecordingsTableLogicInstance = sessionRecordingsTableLogic({ personUUID, isPlaylist: true })
    const { sessionRecordings, sessionRecordingsResponseLoading, hasNext, hasPrev, activeSessionRecordingId } =
        useValues(sessionRecordingsTableLogicInstance)
    const { openSessionPlayer, loadNext, loadPrev } = useActions(sessionRecordingsTableLogicInstance)

    const columns: LemonTableColumns<SessionRecordingType> = [
        {
            title: 'Recordings',
            render: function RenderPlayButton(_: any, sessionRecording: SessionRecordingType) {
                return (
                    <div>
                        {asDisplay(sessionRecording.person)}
                        <div>
                            <span>
                                <TZLabel
                                    time={sessionRecording.start_time}
                                    formatDate="MMMM DD, YYYY"
                                    formatTime="h:mm A"
                                />
                                {` · `}
                                {colonDelimitedDuration(sessionRecording.recording_duration)}
                            </span>
                        </div>
                    </div>
                )
            },
        },
    ]
    return (
        <div className="SessionRecordingPlaylist" data-attr="session-recordings-playlist">
            <div className="SessionRecordingPlaylist__left-column mr-4">
                <LemonTable
                    dataSource={sessionRecordings}
                    columns={columns}
                    loading={sessionRecordingsResponseLoading}
                    onRow={(sessionRecording) => ({
                        onClick: (e) => {
                            // Lets the link to the person open the person's page and not the session recording
                            if (!(e.target as HTMLElement).closest('a')) {
                                console.log('clicked on row', sessionRecording)
                                openSessionPlayer(sessionRecording.id, RecordingWatchedSource.RecordingsList)
                            }
                        },
                    })}
                    rowStatus={(recording) => (activeSessionRecordingId === recording.id ? 'highlighted' : null)}
                    rowClassName="cursor-pointer"
                    data-attr="session-recording-table"
                    data-tooltip="session-recording-table"
                    emptyState="No matching recordings found"
                />
                {(hasPrev || hasNext) && (
                    <Row className="SessionRecordingPlaylist__pagination-control">
                        <Button
                            type="link"
                            disabled={!hasPrev}
                            onClick={() => {
                                loadPrev()
                                window.scrollTo(0, 0)
                            }}
                        >
                            <LeftOutlined /> Previous
                        </Button>
                        <Button
                            type="link"
                            disabled={!hasNext}
                            onClick={() => {
                                loadNext()
                                window.scrollTo(0, 0)
                            }}
                        >
                            Next <RightOutlined />
                        </Button>
                    </Row>
                )}
            </div>
            <div className="SessionRecordingPlaylist__right-column">
                {activeSessionRecordingId ? (
                    <div className="border rounded">
                        <SessionRecordingPlayerV3 playerKey="playlist" sessionRecordingId={activeSessionRecordingId} />
                    </div>
                ) : sessionRecordingsResponseLoading ? (
                    <div className="SessionRecordingPlaylist__loading">
                        <Spinner />
                    </div>
                ) : (
                    <EmptyMessage
                        title="No recording selected"
                        description="Please select a recording from the list on the left"
                        buttonText="Learn more about recordings"
                        buttonHref="https://posthog.com/docs/user-guides/recordings"
                    />
                )}
            </div>
        </div>
    )
}
