import { useActions, useValues } from 'kea'

import { IconPin } from '@posthog/icons'
import { LemonButton, LemonSelect, LemonSelectOption } from '@posthog/lemon-ui'

import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { InsightQueryNode } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

interface IntervalFilterProps {
    disabled?: boolean
}

export function IntervalFilter({ disabled }: IntervalFilterProps): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { interval, enabledIntervals, isIntervalManuallySet } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource, setIsIntervalManuallySet } = useActions(insightVizDataLogic(insightProps))

    return (
        <>
            <span>
                <span className="hidden md:inline">grouped </span>by
            </span>
            {isIntervalManuallySet ? (
                <LemonButton
                    type="secondary"
                    onClick={() => {
                        setIsIntervalManuallySet(false)
                    }}
                    tooltip="Unpin interval"
                    className="flex-1"
                    center
                    size="small"
                    icon={<IconPin color="var(--content-warning)" />}
                    disabledReason={editingDisabledReason}
                >
                    {interval || 'day'}
                </LemonButton>
            ) : (
                <IntervalFilterStandalone
                    disabled={disabled}
                    disabledReason={editingDisabledReason}
                    interval={interval || 'day'}
                    onIntervalChange={(value) => {
                        updateQuerySource({ interval: value } as Partial<InsightQueryNode>)
                    }}
                    options={Object.entries(enabledIntervals).map(([value, { label, disabledReason, hidden }]) => ({
                        value: value as IntervalType,
                        label,
                        hidden,
                        disabledReason,
                    }))}
                />
            )}
        </>
    )
}

interface IntervalFilterStandaloneProps {
    disabled?: boolean
    disabledReason?: string | null
    interval: IntervalType | undefined
    onIntervalChange: (interval: IntervalType) => void
    options?: LemonSelectOption<IntervalType>[]
}

const DEFAULT_OPTIONS: LemonSelectOption<IntervalType>[] = [
    { value: 'hour', label: 'Hour' },
    { value: 'day', label: 'Day' },
    { value: 'week', label: 'Week' },
    { value: 'month', label: 'Month' },
]

export function IntervalFilterStandalone({
    disabled,
    disabledReason,
    interval,
    onIntervalChange,
    options = DEFAULT_OPTIONS,
}: IntervalFilterStandaloneProps): JSX.Element {
    return (
        <LemonSelect
            size="small"
            disabled={disabled}
            disabledReason={disabledReason}
            value={interval || 'day'}
            dropdownMatchSelectWidth={false}
            onChange={onIntervalChange}
            data-attr="interval-filter"
            options={options}
        />
    )
}
