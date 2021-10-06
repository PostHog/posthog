import React from 'react'
import { useActions, useValues } from 'kea'
import { Link } from 'lib/components/Link'
import { humanFriendlyDuration, humanFriendlyDetailedTime } from '~/lib/utils'
import { SessionRecordingType } from '~/types'
import { Button, Card, DatePicker, Row, Space, Table, Typography } from 'antd'
import { sessionRecordingsTableLogic } from './sessionRecordingsTableLogic'
import { PlayCircleOutlined } from '@ant-design/icons'
import { useIsTableScrolling } from 'lib/components/Table/utils'
import { SessionPlayerDrawer } from './SessionPlayerDrawer'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { LeftOutlined, RightOutlined } from '@ant-design/icons'
import moment from 'moment'
import { DurationFilter } from './DurationFilter'

interface SessionRecordingsTableProps {
    personUUID?: string
    isPersonPage?: boolean
}

export function SessionRecordingsTable({ personUUID, isPersonPage = false }: SessionRecordingsTableProps): JSX.Element {
    const sessionRecordingsTableLogicInstance = sessionRecordingsTableLogic({ personUUID })
    const {
        sessionRecordings,
        sessionRecordingsResponseLoading,
        sessionRecordingId,
        filters,
        hasNext,
        hasPrev,
        fromDate,
        toDate,
        durationFilter,
    } = useValues(sessionRecordingsTableLogicInstance)
    const {
        openSessionPlayer,
        closeSessionPlayer,
        setFilters,
        loadNext,
        loadPrev,
        setDateRange,
        setDurationFilter,
    } = useActions(sessionRecordingsTableLogicInstance)
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
                <div style={{ marginBottom: 16 }}>
                    <Typography.Text strong>Filter by events or actions:</Typography.Text>
                    <ActionFilter
                        filters={filters}
                        setFilters={(payload) => {
                            setFilters(payload)
                        }}
                        typeKey={isPersonPage ? `person-${personUUID}` : 'session-recordings'}
                        hideMathSelector={true}
                        buttonCopy="Add event or action filter"
                        horizontalUI
                        customRowPrefix=""
                        hideRename
                        showOr
                    />
                </div>
                <Row style={{ justifyContent: 'flex-end', marginBottom: 16 }}>
                    <Space>
                        <DurationFilter
                            onChange={(newFilter) => {
                                setDurationFilter(newFilter)
                            }}
                            filterValue={durationFilter}
                        />
                        <DatePicker.RangePicker
                            ranges={{
                                'Last 7 Days': [moment().subtract(7, 'd'), null],
                                'Last 30 Days': [moment().subtract(30, 'd'), null],
                                'Last 90 Days': [moment().subtract(90, 'd'), null],
                            }}
                            onChange={(_, dateStrings) => {
                                setDateRange(dateStrings[0], dateStrings[1])
                            }}
                            value={[fromDate ? moment(fromDate) : null, toDate ? moment(toDate) : null]}
                            allowEmpty={[true, true]}
                        />
                    </Space>
                </Row>
                <Table
                    rowKey={(row) => {
                        return `${row.id}-${row.distinct_id}`
                    }}
                    dataSource={sessionRecordings}
                    columns={columns}
                    loading={sessionRecordings.length === 0 && sessionRecordingsResponseLoading}
                    pagination={false}
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
                {(hasPrev || hasNext) && (
                    <div style={{ margin: '3rem auto 10rem', width: 200, display: 'flex', alignItems: 'center' }}>
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
                    </div>
                )}
            </Card>
            {!!sessionRecordingId && <SessionPlayerDrawer isPersonPage={isPersonPage} onClose={closeSessionPlayer} />}
        </div>
    )
}
