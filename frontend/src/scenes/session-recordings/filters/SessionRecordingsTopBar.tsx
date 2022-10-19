import { useActions, useValues } from 'kea'
import { sessionRecordingsListLogic } from '../sessionRecordingsListLogic'
import { DurationFilter } from './DurationFilter'
import { SessionRecordingFilterType } from 'lib/utils/eventUsageLogic'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { SessionRecordingsFiltersToggle } from './SessionRecordingsFilters'
import { sessionRecordingDataLogic } from '../player/sessionRecordingDataLogic'
import { LemonButton } from '@posthog/lemon-ui'
import { asDisplay } from '@posthog/apps-common'
import { IconPlus } from 'lib/components/icons'

interface SessionRecordingsTopBarProps {
    personUUID?: string
    isPersonPage?: boolean
}

export function SessionRecordingsTopBar({
    personUUID,
    isPersonPage = false,
}: SessionRecordingsTopBarProps): JSX.Element {
    const sessionRecordingsListLogicInstance = sessionRecordingsListLogic({ personUUID })
    const { fromDate, toDate, durationFilter } = useValues(sessionRecordingsListLogicInstance)
    const { setDateRange, setDurationFilter, reportRecordingsListFilterAdded } = useActions(
        sessionRecordingsListLogicInstance
    )

    const { activeSessionRecording, propertyFilters } = useValues(sessionRecordingsListLogic({}))
    const { setPropertyFilters } = useActions(sessionRecordingsListLogic({}))
    const { sessionPlayerData } = useValues(
        sessionRecordingDataLogic({ sessionRecordingId: activeSessionRecording?.id })
    )

    const person = sessionPlayerData?.person

    const hasPersonFilter = !!propertyFilters.find(
        (x) =>
            x.key === 'distinct_id' &&
            typeof x.value === 'string' &&
            person?.distinct_ids?.includes(x.value) &&
            x.type === 'person'
    )

    return (
        <div className="flex flex-wrap items-end justify-between gap-4 mb-4">
            <div className="flex items-center gap-2">
                <SessionRecordingsFiltersToggle personUUID={personUUID} isPersonPage={isPersonPage} />

                {!isPersonPage && person && !hasPersonFilter ? (
                    <LemonButton
                        icon={<IconPlus />}
                        size="small"
                        onClick={() => {
                            setPropertyFilters([{ key: 'distinct_id', value: person.distinct_ids[0], type: 'person' }])
                        }}
                    >
                        {asDisplay(person)}
                    </LemonButton>
                ) : null}
            </div>

            <div className="flex items-center gap-4">
                <DateFilter
                    dateFrom={fromDate ?? '-7d'}
                    dateTo={toDate ?? undefined}
                    onChange={(changedDateFrom, changedDateTo) => {
                        reportRecordingsListFilterAdded(SessionRecordingFilterType.DateRange)
                        setDateRange(changedDateFrom ?? undefined, changedDateTo ?? undefined)
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
