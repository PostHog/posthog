import React from 'react'
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration, humanFriendlyDetailedTime } from '~/lib/utils'
import { SessionRecordingType } from '~/types'
import { Button, Card, Col, DatePicker, Row, Table, Typography } from 'antd'
import { sessionRecordingsTableLogic } from './sessionRecordingsTableLogic'
import { PlayCircleOutlined } from '@ant-design/icons'
import { useIsTableScrolling } from 'lib/components/Table/utils'
import { SessionPlayerDrawer } from './SessionPlayerDrawer'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { LeftOutlined, RightOutlined } from '@ant-design/icons'
import moment from 'moment'
import { DurationFilter } from './DurationFilter'
import { PersonHeader } from 'scenes/persons/PersonHeader'

import './SessionRecordingTable.scss'
interface SessionRecordingsTableProps {
    personUUID?: string
    isPersonPage?: boolean
}

function FilterRow({
    filter,
    propertyFiltersButton,
    deleteButton,
}: {
    seriesIndicator?: JSX.Element | string
    suffix?: JSX.Element | string
    filter?: JSX.Element | string
    propertyFiltersButton?: JSX.Element | string
    deleteButton?: JSX.Element | string
    isVertical?: boolean
}): JSX.Element {
    return (
        <Row className="filter-row" wrap={false} align="middle">
            <Col flex="1" className="mr">
                <Row align="middle">{filter}</Row>
            </Col>
            <Col className="mr">{propertyFiltersButton}</Col>
            <Col>{deleteButton}</Col>
        </Row>
    )
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
            title: 'Start time',
            render: function RenderStartTime(sessionRecording: SessionRecordingType) {
                return humanFriendlyDetailedTime(sessionRecording.start_time)
            },
            span: 1,
        },
        {
            title: 'Duration',
            render: function RenderDuration(sessionRecording: SessionRecordingType) {
                return <span>{humanFriendlyDuration(sessionRecording.recording_duration)}</span>
            },
            span: 1,
        },
        {
            title: 'Person',
            key: 'person',
            render: function RenderPersonLink(sessionRecording: SessionRecordingType) {
                return <PersonHeader person={sessionRecording.person} />
            },
            ellipsis: true,
            span: 3,
        },

        {
            key: 'play',
            render: function RenderPlayButton() {
                return <PlayCircleOutlined size={16} />
            },
            width: 32,
        },
    ]
    return (
        <div className="session-recordings-table" data-attr="session-recordings-table">
            <div className="action-filter-container">
                <Typography.Text strong>Filter by events or actions:</Typography.Text>
                <ActionFilter
                    fullWidth={true}
                    filters={filters}
                    setFilters={(payload) => {
                        setFilters(payload)
                    }}
                    typeKey={isPersonPage ? `person-${personUUID}` : 'session-recordings'}
                    hideMathSelector={true}
                    buttonCopy="Add event or action filter"
                    horizontalUI
                    stripeActionRow={false}
                    propertyFilterWrapperClassName="session-recording-action-property-filter"
                    customRowPrefix=""
                    hideRename
                    showOr
                    renderRow={(props) => <FilterRow {...props} />}
                    showNestedArrow={false}
                />
            </div>
            <Row className="time-filter-row">
                <Row className="time-filter">
                    <Typography.Text className="filter-label" strong>
                        Duration
                    </Typography.Text>
                    <DurationFilter
                        onChange={(newFilter) => {
                            setDurationFilter(newFilter)
                        }}
                        filterValue={durationFilter}
                    />
                </Row>
                <Row className="time-filter">
                    <Typography.Text className="filter-label" strong>
                        Start Time
                    </Typography.Text>
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
                </Row>
            </Row>
            <Card>
                <Table
                    rowKey={(row) => {
                        return `${row.id}-${row.distinct_id}`
                    }}
                    dataSource={sessionRecordings}
                    columns={columns}
                    loading={sessionRecordings.length === 0 && sessionRecordingsResponseLoading}
                    pagination={false}
                    onRow={(sessionRecording) => ({
                        onClick: (e) => {
                            // Lets the link to the person open the person's page and not the session recording
                            if (!(e.target as HTMLElement).closest('a')) {
                                openSessionPlayer(sessionRecording.id)
                            }
                        },
                    })}
                    size="small"
                    rowClassName="cursor-pointer"
                    data-attr="session-recording-table"
                    scroll={{ x: tableScrollX }}
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
            </Card>
            {!!sessionRecordingId && <SessionPlayerDrawer isPersonPage={isPersonPage} onClose={closeSessionPlayer} />}
        </div>
    )
}
