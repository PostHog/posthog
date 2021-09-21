import React from 'react'
import { useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { humanFriendlyDetailedTime, humanFriendlyDuration } from '~/lib/utils'
import { SessionRecordingType } from '~/types'

import { ResizableTable, ResizableColumnType } from 'lib/components/ResizableTable'
import { sessionRecordingsTableLogic } from './sessionRecordingsLogic'

export const MATCHING_EVENT_ICON_SIZE = 26

export function SessionRecordingsTable(): JSX.Element {
    const logic = sessionRecordingsTableLogic()
    const { sessionRecordings, sessionRecordingsLoading } = useValues(logic)

    const columns: ResizableColumnType<SessionRecordingType>[] = [
        {
            title: 'Person',
            key: 'person',
            render: function RenderSession(sessionRecording: SessionRecordingType) {
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
            title: 'Session duration',
            render: function RenderDuration(sessionRecording: SessionRecordingType) {
                return <span>{humanFriendlyDuration(sessionRecording.recording_duration)}</span>
            },
            span: 3,
        },
        {
            title: 'Start time',
            render: function RenderStartTime(sessionRecording: SessionRecordingType) {
                return humanFriendlyDetailedTime(sessionRecording.start_time)
            },
            span: 3,
        },
        {
            title: 'End time',
            render: function RenderStartTime(sessionRecording: SessionRecordingType) {
                return humanFriendlyDetailedTime(sessionRecording.end_time)
            },
            span: 3,
        },
    ]

    return (
        <div className="events" data-attr="events-table">
            <ResizableTable
                data-attr="session-recordings-table"
                size="small"
                rowKey="id"
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                rowClassName="cursor-pointer"
                dataSource={sessionRecordings}
                columns={columns}
                loading={sessionRecordingsLoading}
            />
            <div style={{ marginTop: '5rem' }} />
        </div>
    )
}
