import React from 'react'
import { useValues } from 'kea'
import { Table } from 'antd'
import { Link } from 'lib/components/Link'
import moment from 'moment'
import { humanFriendlyDuration, humanFriendlyDetailedTime } from '~/lib/utils'

export function SessionsTable({ logic }) {
    const { sessions } = useValues(logic)
    let columns = [
        {
            title: 'Person',
            key: 'person',
            render: function RenderSession(session) {
                return (
                    <Link to={`/person/${encodeURIComponent(session.person)}`} className="ph-no-capture">
                        {session.person}
                    </Link>
                )
            },
        },
        {
            title: 'Duration',
            render: function RenderDuration(session) {
                return <span>{humanFriendlyDuration(session.length)}</span>
            },
        },
        {
            title: 'Start Time',
            render: function RenderStartTime(session) {
                return <span>{humanFriendlyDetailedTime(session.start_time)}</span>
            },
        },
    ]

    return (
        <div className="events" data-attr="events-table">
            <h1 className="page-header">Sessions</h1>

            <Table
                size="small"
                rowKey={item => item.global_session_id}
                pagination={{ pageSize: 100, hideOnSinglePage: true }}
                dataSource={sessions}
                columns={columns}
            />
            <div style={{ marginTop: '5rem' }} />
        </div>
    )
}
