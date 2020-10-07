import React from 'react'
import { useValues, useActions } from 'kea'
import { Table, Button, Spin, Space, Modal } from 'antd'
import { Link } from 'lib/components/Link'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'
import { humanFriendlyDuration, humanFriendlyDetailedTime, stripHTTP } from '~/lib/utils'
import { SessionDetails } from './SessionDetails'
import { DatePicker } from 'antd'
import moment from 'moment'
import { SessionType } from '~/types'
import { CaretLeftOutlined, CaretRightOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { green } from '@ant-design/colors'
import SessionsPlayer from './SessionsPlayer'
import { eventWithTime } from 'rrweb/typings/types';

export function SessionsTable(): JSX.Element {
    const { sessions, sessionsLoading, nextOffset, isLoadingNext, selectedDate } = useValues(sessionsTableLogic)
    const { fetchNextSessions, dateChanged, previousDay, nextDay } = useActions(sessionsTableLogic)



    function showSessionPlayer(events: eventWithTime[]): void {
        Modal.info({
            centered: true,
            content: <SessionsPlayer events={events}></SessionsPlayer>,
            icon: null,
            okType: 'primary',
            okText: 'Done',
            width: 1000,
        })
    }

    const columns = [
        {
            title: 'Person',
            key: 'person',
            render: function RenderSession(session: SessionType) {
                return (
                    <Link to={`/person/${encodeURIComponent(session.distinct_id)}`} className="ph-no-capture">
                        {session.properties?.email || session.distinct_id}
                    </Link>
                )
            },
            ellipsis: true,
        },
        {
            title: 'Event Count',
            render: function RenderDuration(session: SessionType) {
                return <span>{session.event_count}</span>
            },
        },
        {
            title: 'Duration',
            render: function RenderDuration(session: SessionType) {
                return <span>{humanFriendlyDuration(session.length)}</span>
            },
        },
        {
            title: 'Start Time',
            render: function RenderStartTime(session: SessionType) {
                return <span>{humanFriendlyDetailedTime(session.start_time)}</span>
            },
        },
        {
            title: 'Start Point',
            render: function RenderStartPoint(session: SessionType) {
                return (
                    <span>
                        {session.events.length !== 0 && session.events[0].properties?.$current_url
                            ? stripHTTP(session.events[0].properties.$current_url)
                            : 'N/A'}
                    </span>
                )
            },
            ellipsis: true,
        },
        {
            title: 'End Point',
            render: function RenderEndPoint(session: SessionType) {
                return (
                    <span>
                        {session.events.length !== 0 &&
                        session.events[session.events.length - 1].properties?.$current_url
                            ? stripHTTP(session.events[session.events.length - 1].properties.$current_url)
                            : 'N/A'}
                    </span>
                )
            },
            ellipsis: true,
        },
        {
            title: 'Play Session',
            render: function RenderEndPoint(session: SessionType) {
                return (
                    <span>
                        <PlayCircleOutlined 
                            style={{color: green.primary }}
                            onClick={() => {
                                const snapshotEventsData: eventWithTime[] = session.events.filter(event => event.event === "$snapshot").map(event => event.properties?.data)
                                if (snapshotEventsData.length > 2) {
                                    showSessionPlayer(snapshotEventsData)
                                }
                            }}
                        ></PlayCircleOutlined>
                    </span>
                )
            },
            ellipsis: true,
        },
    ]

    return (
        <div className="events" data-attr="events-table">
            <h1 className="page-header">Sessions By Day</h1>
            <Space className="mb-2">
                <Button onClick={previousDay} icon={<CaretLeftOutlined />} />
                <DatePicker value={selectedDate} onChange={dateChanged} allowClear={false} />
                <Button onClick={nextDay} icon={<CaretRightOutlined />} />
            </Space>
            <Table
                locale={{ emptyText: 'No Sessions on ' + moment(selectedDate).format('YYYY-MM-DD') }}
                data-attr="sessions-table"
                size="small"
                rowKey={(item) => item.global_session_id}
                pagination={{ pageSize: 99999, hideOnSinglePage: true }}
                rowClassName="cursor-pointer"
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
            />
            <div style={{ marginTop: '5rem' }} />
            <div
                style={{
                    margin: '2rem auto 5rem',
                    textAlign: 'center',
                }}
            >
                {(nextOffset || isLoadingNext) && (
                    <Button type="primary" onClick={fetchNextSessions}>
                        {isLoadingNext ? <Spin> </Spin> : 'Load more sessions'}
                    </Button>
                )}
            </div>
        </div>
    )
}
