import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'
import { insightLogic } from 'scenes/insights/insightLogic'

import { insightVizDataLogic } from '../insightVizDataLogic'
import {
    ALL_DAY_NUMBERS,
    DAY_LABELS,
    WEEKDAYS,
    computeDaysOfWeekUpdate,
    daysOfWeekLabel,
    getEffectiveDaysOfWeek,
} from './daysOfWeekFilterUtils'

export function DaysOfWeekFilter(): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { querySource, dateRange, trendsFilter } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource } = useActions(insightVizDataLogic(insightProps))
    const [visible, setVisible] = useState(false)

    const selectedDays = getEffectiveDaysOfWeek(dateRange, trendsFilter)

    const setDays = (days: number[]): void => {
        updateQuerySource(computeDaysOfWeekUpdate(days, querySource, dateRange))
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
                        {ALL_DAY_NUMBERS.map((day) => (
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
