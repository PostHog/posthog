import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'
import { insightLogic } from 'scenes/insights/insightLogic'

import { TrendsQuery } from '~/queries/schema/schema-general'
import { isTrendsQuery } from '~/queries/utils'

import { insightVizDataLogic } from '../insightVizDataLogic'
import { DAY_LABELS, WEEKDAYS, daysOfWeekLabel, getEffectiveDaysOfWeek } from './daysOfWeekFilterUtils'

export function DaysOfWeekFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, dateRange, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const [visible, setVisible] = useState(false)

    const selectedDays = getEffectiveDaysOfWeek(dateRange, trendsFilter)

    const setDays = (days: number[]): void => {
        const daysOfWeek = days.length === 0 || days.length === 7 ? null : [...days].sort((a, b) => a - b)
        const update: Partial<TrendsQuery> = { dateRange: { ...dateRange, daysOfWeek } }
        // daysOfWeek supersedes the legacy display-only weekend toggle
        if (isTrendsQuery(querySource) && querySource.trendsFilter?.hideWeekends) {
            update.trendsFilter = { ...querySource.trendsFilter, hideWeekends: undefined }
        }
        updateQuerySource(update)
    }

    const toggleDay = (day: number): void => {
        setDays(selectedDays.includes(day) ? selectedDays.filter((d) => d !== day) : [...selectedDays, day])
    }

    return (
        <Popover
            visible={visible}
            onClickOutside={() => setVisible(false)}
            overlay={
                <div className="p-2 deprecated-space-y-2">
                    <div className="flex gap-1">
                        {[1, 2, 3, 4, 5, 6, 7].map((day) => (
                            <LemonButton
                                key={day}
                                size="xsmall"
                                type={selectedDays.includes(day) ? 'primary' : 'secondary'}
                                onClick={() => toggleDay(day)}
                                data-attr={`days-of-week-${day}`}
                            >
                                {DAY_LABELS[day]}
                            </LemonButton>
                        ))}
                    </div>
                    <div className="flex gap-1">
                        <LemonButton size="xsmall" type="tertiary" onClick={() => setDays(WEEKDAYS)}>
                            Weekdays only
                        </LemonButton>
                        <LemonButton size="xsmall" type="tertiary" onClick={() => setDays([])}>
                            All days
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <LemonButton
                size="small"
                type="secondary"
                onClick={() => setVisible(!visible)}
                data-attr="days-of-week-filter"
            >
                {daysOfWeekLabel(selectedDays)}
            </LemonButton>
        </Popover>
    )
}
