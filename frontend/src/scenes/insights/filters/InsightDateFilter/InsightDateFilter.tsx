import { useValues, useActions } from 'kea'
import { insightDateFilterLogic } from './insightDateFilterLogic'
import { DateFilter } from 'lib/components/DateFilter/DateFilter'
import { insightLogic } from 'scenes/insights/insightLogic'
import { CalendarOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { Tooltip } from 'antd'

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
        <>
            <span>Date range</span>
            <DateFilter
                dateTo={dateTo ?? undefined}
                dateFrom={dateFrom ?? '-7d' ?? undefined}
                disabled={disabled}
                onChange={(changedDateFrom, changedDateTo) => {
                    setDates(changedDateFrom, changedDateTo)
                }}
                makeLabel={(key) => (
                    <>
                        <CalendarOutlined /> {key}
                        {key == 'All time' && (
                            <Tooltip title={`Only events dated after 2015 will be shown`}>
                                <InfoCircleOutlined className="info-indicator" />
                            </Tooltip>
                        )}
                    </>
                )}
            />
        </>
    )
}
