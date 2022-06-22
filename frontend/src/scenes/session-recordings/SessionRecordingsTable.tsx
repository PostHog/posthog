import React from 'react'
import { useActions, useValues } from 'kea'
import { humanFriendlyDuration } from '~/lib/utils'
import { SessionRecordingType } from '~/types'
import { Button, Row, Typography } from 'antd'
import { sessionRecordingsTableLogic } from './sessionRecordingsTableLogic'
import { PlayCircleOutlined, CalendarOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { SessionPlayerDrawer } from './SessionPlayerDrawer'
import { ActionFilter } from 'scenes/insights/ActionFilter/ActionFilter'
import { LeftOutlined, RightOutlined } from '@ant-design/icons'
import { DurationFilter } from './DurationFilter'
import { PersonHeader } from 'scenes/persons/PersonHeader'
import { RecordingWatchedSource, SessionRecordingFilterType } from 'lib/utils/eventUsageLogic'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { Tooltip } from 'lib/components/Tooltip'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import './SessionRecordingTable.scss'
import { LemonTable, LemonTableColumns } from 'lib/components/LemonTable'
import { TZLabel } from 'lib/components/TimezoneAware'
import { IconFilter } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { MathAvailability } from 'scenes/insights/ActionFilter/ActionFilterRow/ActionFilterRow'

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
        reportRecordingsListFilterAdded,
    } = useActions(sessionRecordingsTableLogicInstance)

    const columns: LemonTableColumns<SessionRecordingType> = [
        {
            title: 'Start time',
            render: function RenderStartTime(_: any, sessionRecording: SessionRecordingType) {
                return <TZLabel time={sessionRecording.start_time} formatDate="MMMM DD, YYYY" formatTime="h:mm A" />
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
                    <div className="space-y-05">
                        <Typography.Text strong>
                            {`Filter by events and actions `}
                            <Tooltip title="Show recordings where all of the events or actions listed below happen.">
                                <InfoCircleOutlined className="info-icon" />
                            </Tooltip>
                        </Typography.Text>
                        <ActionFilter
                            bordered
                            filters={entityFilters}
                            setFilters={(payload) => {
                                reportRecordingsListFilterAdded(SessionRecordingFilterType.EventAndAction)
                                setEntityFilters(payload)
                            }}
                            typeKey={isPersonPage ? `person-${personUUID}` : 'session-recordings'}
                            mathAvailability={MathAvailability.None}
                            buttonCopy="Add filter"
                            hideRename
                            hideDuplicate
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
                    {!isPersonPage && (
                        <div className="mt-2 space-y-05">
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
                                useLemonButton
                                onChange={(properties) => {
                                    reportRecordingsListFilterAdded(SessionRecordingFilterType.PersonAndCohort)
                                    setPropertyFilters(properties)
                                }}
                            />
                        </div>
                    )}
                </div>
                {!showFilters && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        icon={<IconFilter />}
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
                        Filter recordings
                    </LemonButton>
                )}

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
                                reportRecordingsListFilterAdded(SessionRecordingFilterType.DateRange)
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
                                reportRecordingsListFilterAdded(SessionRecordingFilterType.Duration)
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
                emptyState="No matching recordings found"
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
