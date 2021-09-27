import React from 'react'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { humanFriendlyDuration, humanFriendlyDetailedTime } from '~/lib/utils'
import { SessionRecordingType } from '~/types'
import { Card, Table } from 'antd'
import { sessionRecordingsTableLogic } from './sessionRecordingsTableLogic'
import { PlayCircleOutlined } from '@ant-design/icons'
import { useIsTableScrolling } from 'lib/components/Table/utils'
import { SessionPlayerDrawer } from './SessionPlayerDrawer'

interface SessionRecordingsTableProps {
    distinctId?: string
    isPersonPage?: boolean
}

export function SessionRecordingsTable({ distinctId, isPersonPage = false }: SessionRecordingsTableProps): JSX.Element {
    const sessionRecordingsTableLogicInstance = sessionRecordingsTableLogic({ distinctId })
    const { sessionRecordings, sessionRecordingsLoading, sessionRecordingId } = useValues(
        sessionRecordingsTableLogicInstance
    )
    const { openSessionPlayer, closeSessionPlayer } = useActions(sessionRecordingsTableLogicInstance)
    const { tableScrollX } = useIsTableScrolling('lg')

    const columns = [
        {
            key: 'play',
            render: function RenderPlayButton() {
                return <PlayCircleOutlined size={16} />
            },
            width: 32,
        },
        {
            title: 'Session duration',
            render: function RenderDuration(sessionRecording: SessionRecordingType) {
                return <span>{humanFriendlyDuration(sessionRecording.recording_duration)}</span>
            },
            span: 2,
        },
        {
            title: 'Person',
            key: 'person',
            render: function RenderPersonLink(sessionRecording: SessionRecordingType) {
                return (
                    <Link
                        to={`/person/${encodeURIComponent(sessionRecording.distinct_id as string)}`}
                        className="ph-no-capture"
                    >
                        {sessionRecording?.email || sessionRecording.distinct_id}
                    </Link>
                )
            },
            ellipsis: true,
            span: 3,
        },
        {
            title: 'Start time',
            render: function RenderStartTime(sessionRecording: SessionRecordingType) {
                return humanFriendlyDetailedTime(sessionRecording.start_time)
            },
            span: 2,
        },
        {
            title: 'End time',
            render: function RenderStartTime(sessionRecording: SessionRecordingType) {
                return humanFriendlyDetailedTime(sessionRecording.end_time)
            },
            span: 2,
        },
    ]

    return (
        <div className="events" data-attr="events-table">
            <Card>
                <Table
                    rowKey="id"
                    dataSource={sessionRecordings}
                    columns={columns}
                    loading={sessionRecordings.length === 0 && sessionRecordingsLoading}
                    pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                    onRow={(sessionRecording) => ({
                        onClick: () => {
                            openSessionPlayer(sessionRecording.id)
                        },
                    })}
                    size="small"
                    rowClassName="cursor-pointer"
                    data-attr="session-recording-table"
                    scroll={{ x: tableScrollX }}
                />
            </Card>
            <div style={{ marginTop: '5rem' }} />
            {!!sessionRecordingId && <SessionPlayerDrawer isPersonPage={isPersonPage} onClose={closeSessionPlayer} />}
        </div>
    )
}
