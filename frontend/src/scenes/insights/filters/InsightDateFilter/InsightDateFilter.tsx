import { useValues, useActions } from 'kea'
import { insightDateFilterLogic } from './insightDateFilterLogic'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { Tooltip } from 'antd'
import { IconCalendar, IconInfo } from '@posthog/icons'

type InsightDateFilterProps = {
    disabled: boolean
}

export function InsightDateFilter({ disabled }: InsightDateFilterProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const {
        dates: { dateFrom, dateTo },
    } = useValues(insightDateFilterLogic(insightProps))
    const { setDates } = useActions(insightDateFilterLogic(insightProps))

    return (
        <DateFilter
            dateTo={dateTo ?? undefined}
            dateFrom={dateFrom ?? '-7d' ?? undefined}
            disabled={disabled}
            onChange={(changedDateFrom, changedDateTo) => {
                setDates(changedDateFrom, changedDateTo)
            }}
            makeLabel={(key) => (
                <>
                    <IconCalendar /> {key}
                    {key == 'All time' && (
                        <Tooltip title={`Only events dated after 2015 will be shown`}>
                            <IconInfo className="info-indicator" />
                        </Tooltip>
                    )}
                </>
            )}
        />
    )
}
