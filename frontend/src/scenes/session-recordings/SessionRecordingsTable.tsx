import React from 'react'
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration } from '~/lib/utils'
import { SessionRecordingType } from '~/types'
import { Button, Row } from 'antd'
import { sessionRecordingsTableLogic } from './sessionRecordingsTableLogic'
import { PlayCircleOutlined } from '@ant-design/icons'
import { SessionPlayerDrawer } from './SessionPlayerDrawer'
import { LeftOutlined, RightOutlined } from '@ant-design/icons'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import './SessionRecordingTable.scss'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { TZLabel } from 'lib/components/TimezoneAware'
interface SessionRecordingsTableProps {
    personUUID?: string
    isPersonPage?: boolean
}

export function SessionRecordingsTable({ personUUID, isPersonPage = false }: SessionRecordingsTableProps): JSX.Element {
    const sessionRecordingsTableLogicInstance = sessionRecordingsTableLogic({ personUUID })
    const { sessionRecordings, sessionRecordingsResponseLoading, activeSessionRecordingId, hasNext, hasPrev } =
        useValues(sessionRecordingsTableLogicInstance)
    const { openSessionPlayer, closeSessionPlayer, loadNext, loadPrev } = useActions(
        sessionRecordingsTableLogicInstance
    )

    const columns: LemonTableColumns<SessionRecordingType> = [
        {
            title: 'Start time',
            render: function RenderStartTime(_: any, sessionRecording: SessionRecordingType) {
                return <TZLabel time={sessionRecording.start_time} formatDate="MMMM DD, YYYY" formatTime="h:mm A" />
            },
        },
        {
            title: 'Duration',
            render: function RenderDuration(_: any, sessionRecording: SessionRecordingType) {
                return <span>{humanFriendlyDuration(sessionRecording.recording_duration)}</span>
            },
        },
        {
            title: 'Person',
            key: 'person',
            render: function RenderPersonLink(_: any, sessionRecording: SessionRecordingType) {
                return <PersonHeader withIcon person={sessionRecording.person} />
            },
        },

        {
            render: function RenderPlayButton(_: any, sessionRecording: SessionRecordingType) {
                return (
                    <div className="play-button-container">
                        <Button
                            className={sessionRecording.viewed ? 'play-button viewed' : 'play-button'}
                            data-attr="session-recordings-button"
                            icon={<PlayCircleOutlined />}
                        >
                            Watch recording
                        </Button>
                    </div>
                )
            },
        },
    ]
    return (
        <div className="session-recordings-table" data-attr="session-recordings-table">
            <LemonTable
                dataSource={sessionRecordings}
                columns={columns}
                loading={sessionRecordingsResponseLoading}
                onRow={(sessionRecording) => ({
                    onClick: (e) => {
                        // Lets the link to the person open the person's page and not the session recording
                        if (!(e.target as HTMLElement).closest('a')) {
                            openSessionPlayer(sessionRecording.id, RecordingWatchedSource.RecordingsList)
                        }
                    },
                })}
                rowClassName="cursor-pointer"
                data-attr="session-recording-table"
                data-tooltip="session-recording-table"
                emptyState="No matching recordings found"
            />
            {(hasPrev || hasNext) && (
                <Row className="pagination-control">
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
            <div style={{ marginBottom: 64 }} />
            {!!activeSessionRecordingId && (
                <SessionPlayerDrawer isPersonPage={isPersonPage} onClose={closeSessionPlayer} />
            )}
        </div>
    )
}
