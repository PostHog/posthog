import React from 'react'
import { useValues, useActions } from 'kea'
import { Table, Button, Spin } from 'antd'
import { Link } from 'lib/components/Link'
import { humanFriendlyDuration, humanFriendlyDetailedTime } from '~/lib/utils'
import _ from 'lodash'
import { SessionDetails } from './SessionDetails'
import { DatePicker } from 'antd'
import moment from 'moment'

export function SessionsTable({ logic }) {
    const { sessions, sessionsLoading, offset, isLoadingNext, selectedDate } = useValues(logic)
    const { fetchNextSessions, dateChanged } = useActions(logic)
    let columns = [
        {
            title: 'Person',
            key: 'person',
            render: function RenderSession(session) {
                return (
                    <Link to={`/person/${encodeURIComponent(session.distinct_id)}`} className="ph-no-capture">
                        {session.properties.email || session.distinct_id}
                    </Link>
                )
            },
            ellipsis: true,
        },
        {
            title: 'Event Count',
            render: function RenderDuration(session) {
                return <span>{session.event_count}</span>
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
        {
            title: 'Start Point',
            render: function RenderStartPoint(session) {
                return (
                    <span>
                        {!_.isEmpty(session.events) && _.first(session.events).properties?.$current_url
                            ? session.events[0].properties.$current_url
                            : 'N/A'}
                    </span>
                )
            },
            ellipsis: true,
        },
        {
            title: 'End Point',
            render: function RenderEndPoint(session) {
                return (
                    <span>
                        {!_.isEmpty(session.events) && _.last(session.events).properties?.$current_url
                            ? _.last(session.events).properties.$current_url
                            : 'N/A'}
                    </span>
                )
            },
            ellipsis: true,
        },
    ]

    return (
        <div className="events" data-attr="events-table">
            <h1 className="page-header">Sessions By Day</h1>
            <DatePicker className="mb-2" value={selectedDate} onChange={dateChanged} allowClear={false}></DatePicker>
            <Table
                locale={{ emptyText: 'No Sessions on ' + moment(selectedDate).format('YYYY-MM-DD') }}
                data-attr="sessions-table"
                size="small"
                rowKey={item => item.global_session_id}
                pagination={{ pageSize: 100, hideOnSinglePage: true }}
                dataSource={sessions}
                columns={columns}
                loading={sessionsLoading}
                expandable={{
                    expandedRowRender: function renderExpand({ events }) {
                        return <SessionDetails events={events} />
                    },
                    rowExpandable: () => true,
                    expandRowByClick: true,
                }}
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
            />
            <div style={{ marginTop: '5rem' }} />
            {offset || isLoadingNext ? (
                <div
                    style={{
                        margin: '2rem auto 5rem',
                        textAlign: 'center',
                    }}
                >
                    <Button type="primary" onClick={fetchNextSessions}>
                        {isLoadingNext ? <Spin> </Spin> : 'Load more sessions'}
                    </Button>
                </div>
            ) : (
                sessions.length > 0 && (
                    <span> {'No more Sessions on ' + moment(selectedDate).format('YYYY-MM-DD')}</span>
                )
            )}
        </div>
    )
}
