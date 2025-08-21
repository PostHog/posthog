import { useActions, useValues } from 'kea'

import { IconCalendar } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { DateFilter } from '../DateFilter/DateFilter'
import { appMetricsLogic } from './appMetricsLogic'

export type AppMetricsFiltersProps = {
    logicKey: string
}

export function AppMetricsFilters({ logicKey }: AppMetricsFiltersProps): JSX.Element {
    const logic = appMetricsLogic({ logicKey })
    const { params } = useValues(logic)
    const { setParams } = useActions(logic)

    return (
        <div className="flex flex-row gap-2 mb-2 flex-wrap">
            <LemonSelect
                options={[
                    { label: 'Minute', value: 'minute' },
                    { label: 'Hourly', value: 'hour' },
                    { label: 'Daily', value: 'day' },
                ]}
                size="small"
                value={params.interval}
                onChange={(value) => setParams({ interval: value })}
            />
            <DateFilter
                dateTo={params.dateTo}
                dateFrom={params.dateFrom}
                onChange={(from, to) => setParams({ dateFrom: from || undefined, dateTo: to || undefined })}
                allowedRollingDateOptions={['days', 'weeks', 'months', 'years']}
                makeLabel={(key) => (
                    <>
                        <IconCalendar /> {key}
                    </>
                )}
            />
        </div>
    )
}
