import { useActions, useValues } from 'kea'

import { IconCalendar, IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { retentionLogic } from 'scenes/retention/retentionLogic'

export function RetentionDatePicker(): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { dateRange, dateMappings } = useValues(retentionLogic(insightProps))
    const { updateDateRange } = useActions(retentionLogic(insightProps))

    return (
        <DateFilter
            dateTo={dateRange?.date_to ?? undefined}
            dateFrom={dateRange?.date_from ?? undefined}
            onChange={(date_from, date_to, explicit_date) => {
                updateDateRange({ date_from, date_to, explicitDate: explicit_date })
            }}
            dateOptions={dateMappings}
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
            disabledReason={editingDisabledReason}
        />
    )
}
