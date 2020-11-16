import React from 'react'
import { useValues, useActions } from 'kea'
import { Table, Button, Spin, Space, Tooltip } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { Link } from 'lib/components/Link'
import { sessionsTableLogic } from 'scenes/sessions/sessionsTableLogic'
import { humanFriendlyDuration, humanFriendlyDetailedTime, stripHTTP } from '~/lib/utils'
import { SessionDetails } from './SessionDetails'
import { DatePicker } from 'antd'
import moment from 'moment'
import { SessionType } from '~/types'
import { CaretLeftOutlined, CaretRightOutlined } from '@ant-design/icons'
import SessionsPlayerButton from './SessionsPlayerButton'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import rrwebBlockClass from 'lib/utils/rrwebBlockClass'
import SessionsPlayerDrawer from 'scenes/sessions/SessionsPlayerDrawer'
import { PageHeader } from 'lib/components/PageHeader'

interface SessionsTableProps {
    personIds?: string[]
    isPersonPage?: boolean
}

export function SessionsTable({ personIds, isPersonPage = false }: SessionsTableProps): JSX.Element {
    const logic = sessionsTableLogic({ personIds })
    const {
        sessions,
        sessionsLoading,
        nextOffset,
        isLoadingNext,
        selectedDate,
        properties,
        sessionRecordingId,
    } = useValues(logic)
    const { fetchNextSessions, previousDay, nextDay, setFilters } = useActions(logic)

    const columns = [
        {
            title: 'Person',
            key: 'person',
            render: function RenderSession(session: SessionType) {
                return (
                    <Link
                        to={`/person/${encodeURIComponent(session.distinct_id)}`}
                        className={rrwebBlockClass + ' ph-no-capture'}
                    >
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
            title: (
                <span>
                    <Tooltip title="Enable session recording from Project > Settings">
                        <span>
                            Play session
                            <InfoCircleOutlined style={{ marginLeft: 6 }} />
                        </span>
                    </Tooltip>
                </span>
            ),
            render: function RenderEndPoint(session: SessionType) {
                return <SessionsPlayerButton session={session} />
            },
            ellipsis: true,
        },
    ]

    return (
        <div className="events" data-attr="events-table">
            {!isPersonPage && <PageHeader title="Sessions By Day" />}
            <Space className="mb-05">
                <Button onClick={previousDay} icon={<CaretLeftOutlined />} />
                <DatePicker
                    value={selectedDate}
                    onChange={(date) => setFilters(properties, date, sessionRecordingId)}
                    allowClear={false}
                />
                <Button onClick={nextDay} icon={<CaretRightOutlined />} />
            </Space>
            <PropertyFilters pageKey={'sessions-' + (personIds && JSON.stringify(personIds))} />
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
            {!!sessionRecordingId && <SessionsPlayerDrawer />}
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
