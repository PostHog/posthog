import React from 'react'
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration } from '~/lib/utils'
import { SessionRecordingType } from '~/types'
import { Button, Col, Row, Typography } from 'antd'
import { sessionRecordingsTableLogic } from './sessionRecordingsTableLogic'
import { PlayCircleOutlined, CalendarOutlined, InfoCircleOutlined, FilterOutlined } from '@ant-design/icons'
import { SessionPlayerDrawer } from './SessionPlayerDrawer'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { LeftOutlined, RightOutlined } from '@ant-design/icons'
import { DurationFilter } from './DurationFilter'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { RecordingWatchedSource } from 'lib/utils/eventUsageLogic'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { Tooltip } from 'lib/components/Tooltip'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyFilters } from 'lib/components/PropertyFilters'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import './SessionRecordingTable.scss'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { TZLabel } from 'lib/components/TimezoneAware'

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
        propertyFilters,
        hasNext,
        hasPrev,
        fromDate,
        toDate,
        durationFilter,
        showFilters,
    } = useValues(sessionRecordingsTableLogicInstance)
    const {
        openSessionPlayer,
        closeSessionPlayer,
        setEntityFilters,
        setPropertyFilters,
        loadNext,
        loadPrev,
        setDateRange,
        setDurationFilter,
        enableFilter,
    } = useActions(sessionRecordingsTableLogicInstance)
    const { preflight } = useValues(preflightLogic)

    const columns: LemonTableColumns<SessionRecordingType> = [
        {
            title: 'Start time',
            render: function RenderStartTime(_: any, sessionRecording: SessionRecordingType) {
                return <TZLabel time={sessionRecording.start_time} formatString="MMMM DD, YYYY h:mm" />
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
            <Row className="filter-row">
                <div className="filter-container" style={{ display: showFilters ? undefined : 'none' }}>
                    <div>
                        <Typography.Text strong>
                            {`Filter by events and actions `}
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
                            actionsTaxonomicGroupTypes={[
                                TaxonomicFilterGroupType.Actions,
                                TaxonomicFilterGroupType.Events,
                            ]}
                            propertiesTaxonomicGroupTypes={[
                                TaxonomicFilterGroupType.EventProperties,
                                TaxonomicFilterGroupType.Elements,
                            ]}
                        />
                    </div>
                    {!isPersonPage && preflight?.is_clickhouse_enabled && (
                        <div className="mt-2">
                            <Typography.Text strong>
                                {`Filter by persons and cohorts `}
                                <Tooltip title="Show recordings by persons who match the set criteria">
                                    <InfoCircleOutlined className="info-icon" />
                                </Tooltip>
                            </Typography.Text>
                            <PropertyFilters
                                popoverPlacement="bottomRight"
                                pageKey={isPersonPage ? `person-${personUUID}` : 'session-recordings'}
                                taxonomicGroupTypes={[
                                    TaxonomicFilterGroupType.PersonProperties,
                                    TaxonomicFilterGroupType.Cohorts,
                                ]}
                                propertyFilters={propertyFilters}
                                onChange={(properties) => {
                                    setPropertyFilters(properties)
                                }}
                            />
                        </div>
                    )}
                </div>
                <Button
                    style={{ display: showFilters ? 'none' : undefined }}
                    onClick={() => {
                        enableFilter()
                        if (isPersonPage) {
                            const entityFilterButtons = document.querySelectorAll('.entity-filter-row button')
                            if (entityFilterButtons.length > 0) {
                                ;(entityFilterButtons[0] as HTMLElement).click()
                            }
                        }
                    }}
                >
                    <FilterOutlined /> Filter recordings
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
                            defaultValue="Last 7 days"
                            bordered={true}
                            dateFrom={fromDate ?? undefined}
                            dateTo={toDate ?? undefined}
                            onChange={(changedDateFrom, changedDateTo) => {
                                setDateRange(changedDateFrom, changedDateTo)
                            }}
                            dateOptions={{
                                Custom: { values: [] },
                                'Last 24 hours': { values: ['-24h'] },
                                'Last 7 days': { values: ['-7d'] },
                                'Last 21 days': { values: ['-21d'] },
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
            {!!sessionRecordingId && <SessionPlayerDrawer isPersonPage={isPersonPage} onClose={closeSessionPlayer} />}
        </div>
    )
}
