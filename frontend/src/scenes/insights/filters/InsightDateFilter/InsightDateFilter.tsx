import { IconCalendar, IconInfo } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

type InsightDateFilterProps = {
    disabled: boolean
}

export function InsightDateFilter({ disabled }: InsightDateFilterProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { dateRange } = useValues(insightVizDataLogic(insightProps))
    const { updateDateRange } = useActions(insightVizDataLogic(insightProps))

    return (
        <DateFilter
            dateTo={dateRange?.date_to ?? undefined}
            dateFrom={dateRange?.date_from ?? '-7d'}
            disabled={disabled}
            onChange={(date_from, date_to) => {
                updateDateRange({ date_from, date_to })
            }}
            makeLabel={(key) => (
                <>
                    <IconCalendar /> {key}
                    {key == 'All time' && (
                        <Tooltip title="Only events dated after 2015 will be shown">
                            <span>
                                <IconInfo className="info-indicator" />
                            </span>
                        </Tooltip>
                    )}
                </>
            )}
        />
    )
}
