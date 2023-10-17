import { intervalFilterLogic } from './intervalFilterLogic'
import { useActions, useValues } from 'kea'
import { IntervalType } from '~/types'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonSelect } from '@posthog/lemon-ui'

interface IntervalFilterProps {
    disabled?: boolean
}

export function IntervalFilter({ disabled }: IntervalFilterProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { interval, enabledIntervals } = useValues(intervalFilterLogic(insightProps))
    const { setInterval } = useActions(intervalFilterLogic(insightProps))

    return (
        <>
            <span>
                <span className="hide-lte-md">grouped </span>by
            </span>
            <LemonSelect
                size={'small'}
                disabled={disabled}
                value={interval || 'day'}
                dropdownMatchSelectWidth={false}
                onChange={(value) => {
                    if (value) {
                        setInterval(String(value) as IntervalType)
                    }
                }}
                data-attr="interval-filter"
                options={Object.entries(enabledIntervals).map(([value, { label, disabledReason }]) => ({
                    value,
                    label,
                    disabledReason,
                }))}
            />
        </>
    )
}
