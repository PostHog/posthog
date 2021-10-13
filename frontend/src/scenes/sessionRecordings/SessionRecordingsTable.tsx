import React from 'react'
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration, humanFriendlyDetailedTime } from '~/lib/utils'
import { SessionRecordingType } from '~/types'
import { Button, Card, Col, Row, Table, Typography } from 'antd'
import { sessionRecordingsTableLogic } from './sessionRecordingsTableLogic'
import { PlayCircleOutlined, CalendarOutlined, InfoCircleOutlined, FilterOutlined } from '@ant-design/icons'
import { useIsTableScrolling } from 'lib/components/Table/utils'
import { SessionPlayerDrawer } from './SessionPlayerDrawer'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { LeftOutlined, RightOutlined } from '@ant-design/icons'
import { DurationFilter } from './DurationFilter'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { Tooltip } from 'lib/components/Tooltip'
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
        <Row className="entity-filter-row" wrap={false} align="middle">
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
        entityFilters,
        hasNext,
        hasPrev,
        fromDate,
        toDate,
        durationFilter,
        showEntityFilter,
    } = useValues(sessionRecordingsTableLogicInstance)
    const {
        openSessionPlayer,
        closeSessionPlayer,
        setEntityFilters,
        loadNext,
        loadPrev,
        setDateRange,
        setDurationFilter,
        enableEntityFilter,
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
            render: function RenderPlayButton(sessionRecording: SessionRecordingType) {
                return (
                    <div className="play-button-container">
                        <Button
                            className={sessionRecording.viewed ? 'play-button viewed' : 'play-button'}
                            data-attr="session-recordings-button"
                            icon={<PlayCircleOutlined />}
                        >
                            Watch session
                        </Button>
                    </div>
                )
            },
        },
    ]
    return (
        <div className="session-recordings-table" data-attr="session-recordings-table">
            <Row className="filter-row">
                <div className="action-filter-container" style={{ display: showEntityFilter ? undefined : 'none' }}>
                    <Typography.Text strong>
                        {`Filter by events or actions `}
                        <Tooltip title="Show recordings where all of the events or actions listed below happen.">
                            <InfoCircleOutlined className="info-icon" />
                        </Tooltip>
                    </Typography.Text>
                    <ActionFilter
                        fullWidth={true}
                        filters={entityFilters}
                        setFilters={(payload) => {
                            setEntityFilters(payload)
                        }}
                        typeKey={isPersonPage ? `person-${personUUID}` : 'session-recordings'}
                        hideMathSelector={true}
                        buttonCopy="Add another filter"
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
                <Button
                    style={{ display: showEntityFilter ? 'none' : undefined }}
                    onClick={() => {
                        enableEntityFilter()

                        const entityFilterButtons = document.querySelectorAll('.entity-filter-row button')
                        if (entityFilterButtons.length > 0) {
                            ;(entityFilterButtons[0] as HTMLElement).click()
                        }
                    }}
                >
                    <FilterOutlined /> Filter by events and actions
                </Button>

                <Row className="time-filter-row">
                    <Row className="time-filter">
                        <DateFilter
                            makeLabel={(key) => (
                                <>
                                    <CalendarOutlined />
                                    <span> {key}</span>
                                </>
                            )}
                            defaultValue="Last 30 days"
                            bordered={true}
                            dateFrom={fromDate ?? undefined}
                            dateTo={toDate ?? undefined}
                            onChange={(changedDateFrom, changedDateTo) => {
                                setDateRange(changedDateFrom, changedDateTo)
                            }}
                        />
                    </Row>
                    <Row className="time-filter">
                        <Typography.Text className="filter-label">Duration</Typography.Text>
                        <DurationFilter
                            onChange={(newFilter) => {
                                setDurationFilter(newFilter)
                            }}
                            initialFilter={durationFilter}
                            pageKey={isPersonPage ? `person-${personUUID}` : 'session-recordings'}
                        />
                    </Row>
                </Row>
            </Row>
            <Card>
                <Table
                    rowKey={(row) => {
                        return `${row.id}-${row.distinct_id}`
                    }}
                    dataSource={sessionRecordings}
                    columns={columns}
                    loading={sessionRecordingsResponseLoading}
                    pagination={false}
                    onRow={(sessionRecording) => ({
                        onClick: (e) => {
                            // Lets the link to the person open the person's page and not the session recording
                            if (!(e.target as HTMLElement).closest('a')) {
                                openSessionPlayer(sessionRecording.id, RecordingWatchedSource.RecordingsList)
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
