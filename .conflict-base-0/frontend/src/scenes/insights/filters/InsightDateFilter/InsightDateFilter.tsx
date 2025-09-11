import { useActions, useValues } from 'kea'

import { IconCalendar, IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { dateMapping } from 'lib/utils'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

type InsightDateFilterProps = {
    disabled: boolean
}

export function InsightDateFilter({ disabled }: InsightDateFilterProps): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)

    const { isTrends, dateRange } = useValues(insightVizDataLogic(insightProps))
    const { updateDateRange } = useActions(insightVizDataLogic(insightProps))

    return (
        <DateFilter
            dateTo={dateRange?.date_to ?? undefined}
            dateFrom={dateRange?.date_from ?? '-7d'}
            allowTimePrecision
            disabled={disabled}
            disabledReason={editingDisabledReason}
            onChange={(date_from, date_to, explicit_date) => {
                updateDateRange({ date_from, date_to, explicitDate: explicit_date })
            }}
            dateOptions={dateMapping}
            allowedRollingDateOptions={isTrends ? ['hours', 'days', 'weeks', 'months', 'years'] : undefined}
            makeLabel={(key) => (
                <>
                    <IconCalendar /> {key}
                    {key == 'All time' && (
                        <Tooltip title="Only events dated after 2015 will be shown">
                            <IconInfo className="info-indicator" />
                        </Tooltip>
                    )}
                </>
            )}
        />
    )
}
