import React from 'react'
import { useActions, useValues } from 'kea'
import { Row, Typography } from 'antd'
import { sessionRecordingsTableLogic } from './sessionRecordingsTableLogic'
import { CalendarOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { DurationFilter } from './DurationFilter'
import { SessionRecordingFilterType } from 'lib/utils/eventUsageLogic'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { Tooltip } from 'lib/components/Tooltip'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import './SessionRecordingFilters.scss'

import { IconFilter } from 'lib/components/icons'
import { LemonButton } from 'lib/components/LemonButton'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

interface SessionRecordingsTableProps {
    personUUID?: string
    isPersonPage?: boolean
}

export function SessionRecordingsFilters({
    personUUID,
    isPersonPage = false,
}: SessionRecordingsTableProps): JSX.Element {
    const sessionRecordingsTableLogicInstance = sessionRecordingsTableLogic({ personUUID })
    const { entityFilters, propertyFilters, fromDate, toDate, durationFilter, showFilters } = useValues(
        sessionRecordingsTableLogicInstance
    )
    const {
        setEntityFilters,
        setPropertyFilters,
        setDateRange,
        setDurationFilter,
        enableFilter,
        reportRecordingsListFilterAdded,
    } = useActions(sessionRecordingsTableLogicInstance)

    return (
        <div className="SessionRecordingFilters">
            <Row className="filter-row">
                <div className="filter-container" style={{ display: showFilters ? undefined : 'none' }}>
                    <div className="space-y-2">
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
                                TaxonomicFilterGroupType.EventFeatureFlags,
                                TaxonomicFilterGroupType.Elements,
                            ]}
                        />
                    </div>
                    {!isPersonPage && (
                        <div className="mt-8 space-y-2">
                            <Typography.Text strong>
                                {`Filter by persons and cohorts `}
                                <Tooltip title="Show recordings by persons who match the set criteria">
                                    <InfoCircleOutlined className="info-icon" />
                                </Tooltip>
                            </Typography.Text>
                            <PropertyFilters
                                pageKey={isPersonPage ? `person-${personUUID}` : 'session-recordings'}
                                taxonomicGroupTypes={[
                                    TaxonomicFilterGroupType.PersonProperties,
                                    TaxonomicFilterGroupType.Cohorts,
                                ]}
                                propertyFilters={propertyFilters}
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
                            dateFrom={fromDate ?? undefined}
                            dateTo={toDate ?? undefined}
                            onChange={(changedDateFrom, changedDateTo) => {
                                reportRecordingsListFilterAdded(SessionRecordingFilterType.DateRange)
                                setDateRange(changedDateFrom, changedDateTo)
                            }}
                            dateOptions={[
                                { key: 'Custom', values: [] },
                                { key: 'Last 24 hours', values: ['-24h'] },
                                { key: 'Last 7 days', values: ['-7d'] },
                                { key: 'Last 21 days', values: ['-21d'] },
                            ]}
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
        </div>
    )
}
