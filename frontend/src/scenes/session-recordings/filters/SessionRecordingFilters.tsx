import React from 'react'
import { useActions, useValues } from 'kea'
import { sessionRecordingsTableLogic } from '../sessionRecordingsTableLogic'
import { DurationFilter } from '../DurationFilter'
import { SessionRecordingFilterType } from 'lib/utils/eventUsageLogic'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { SessionRecordingsEventFilters, SessionRecordingsEventFiltersToggle } from './SessionRecordingEventFilters'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

interface SessionRecordingsTableProps {
    personUUID?: string
    isPersonPage?: boolean
}

export function SessionRecordingsFilters({
    personUUID,
    isPersonPage = false,
}: SessionRecordingsTableProps): JSX.Element {
    const sessionRecordingsTableLogicInstance = sessionRecordingsTableLogic({ personUUID })
    const { fromDate, toDate, durationFilter } = useValues(sessionRecordingsTableLogicInstance)
    const { setDateRange, setDurationFilter, reportRecordingsListFilterAdded } = useActions(
        sessionRecordingsTableLogicInstance
    )

    const { featureFlags } = useValues(featureFlagLogic)

    return (
        <div className="flex flex-wrap items-end justify-between gap-4 mb-4">
            {!featureFlags[FEATURE_FLAGS.SESSION_RECORDINGS_PLAYLIST] ? (
                <SessionRecordingsEventFilters personUUID={personUUID} isPersonPage={isPersonPage} />
            ) : (
                <SessionRecordingsEventFiltersToggle personUUID={personUUID} isPersonPage={isPersonPage} />
            )}

            <div className="flex items-center gap-4">
                <DateFilter
                    dateFrom={fromDate ?? '-7d'}
                    dateTo={toDate ?? undefined}
                    onChange={(changedDateFrom, changedDateTo) => {
                        reportRecordingsListFilterAdded(SessionRecordingFilterType.DateRange)
                        setDateRange(changedDateFrom, changedDateTo ?? undefined)
                    }}
                    dateOptions={[
                        { key: 'Custom', values: [] },
                        { key: 'Last 24 hours', values: ['-24h'] },
                        { key: 'Last 7 days', values: ['-7d'] },
                        { key: 'Last 21 days', values: ['-21d'] },
                    ]}
                />
                <div className="flex gap-2">
                    <LemonLabel>Duration</LemonLabel>
                    <DurationFilter
                        onChange={(newFilter) => {
                            reportRecordingsListFilterAdded(SessionRecordingFilterType.Duration)
                            setDurationFilter(newFilter)
                        }}
                        initialFilter={durationFilter}
                        pageKey={isPersonPage ? `person-${personUUID}` : 'session-recordings'}
                    />
                </div>
            </div>
        </div>
    )
}
