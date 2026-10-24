import { useActions, useValues } from 'kea'

import { IconPin } from '@posthog/icons'
import {
    LemonButton,
    LemonSelect,
    LemonSelectOption,
    LemonSelectOptionLeaf,
    isLemonSelectOptionNode,
} from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { InsightQueryNode } from '~/queries/schema/schema-general'
import { IntervalType } from '~/types'

import { QuillIntervalFilterStandalone } from './QuillIntervalFilterStandalone'

interface IntervalFilterProps {
    disabled?: boolean
}

export function IntervalFilter({ disabled }: IntervalFilterProps): JSX.Element {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { interval, enabledIntervals, isIntervalManuallySet } = useValues(insightVizDataLogic(insightProps))
    const { updateQuerySource, setIsIntervalManuallySet } = useActions(insightVizDataLogic(insightProps))
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    return (
        <span className="flex items-center gap-2">
            {todayRailNav ? (
                <Text size="xs" render={<span className="@max-[780px]:hidden" />}>
                    <span className="hidden md:inline">grouped </span>by
                </Text>
            ) : (
                <span className="@max-[780px]:hidden">
                    <span className="hidden md:inline">grouped </span>by
                </span>
            )}
            {isIntervalManuallySet ? (
                todayRailNav ? (
                    <Button
                        variant="outline"
                        onClick={() => setIsIntervalManuallySet(false)}
                        tooltip="Unpin interval"
                        disabledReason={editingDisabledReason}
                    >
                        <IconPin className="text-warning-foreground" />
                        {interval || 'day'}
                    </Button>
                ) : (
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
                )
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
        </span>
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <QuillIntervalFilterStandalone
                disabled={disabled}
                disabledReason={disabledReason}
                interval={interval || 'day'}
                onIntervalChange={onIntervalChange}
                options={options.filter(
                    (option): option is LemonSelectOptionLeaf<IntervalType> => !isLemonSelectOptionNode(option)
                )}
            />
        )
    }

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
