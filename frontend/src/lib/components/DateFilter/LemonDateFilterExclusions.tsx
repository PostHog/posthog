import clsx from 'clsx'
import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonSwitch, Popover } from '@posthog/lemon-ui'

import {
    type DateFilterExclusions,
    dateFilterExclusionsSummary,
} from 'lib/components/DateFilter/DateFilterExclusionsControl'

const DAYS_OF_WEEK: { day: string; label: string; name: string }[] = [
    { day: '1', label: 'M', name: 'Monday' },
    { day: '2', label: 'T', name: 'Tuesday' },
    { day: '3', label: 'W', name: 'Wednesday' },
    { day: '4', label: 'T', name: 'Thursday' },
    { day: '5', label: 'F', name: 'Friday' },
    { day: '6', label: 'S', name: 'Saturday' },
    { day: '7', label: 'S', name: 'Sunday' },
]

export function LemonDateFilterExclusions({
    exclusions,
    onChange,
    showDays,
    showIncomplete,
    size,
}: {
    exclusions: DateFilterExclusions
    onChange: (exclusions: DateFilterExclusions) => void
    showDays: boolean
    showIncomplete: boolean
    size?: 'small' | 'medium'
}): JSX.Element {
    const [visible, setVisible] = useState(false)
    const summary = dateFilterExclusionsSummary(exclusions)
    return (
        <Popover
            visible={visible}
            onClickOutside={() => setVisible(false)}
            placement="right-end"
            // side fallbacks only, so collision handling keeps the flyout beside the row instead of flipping above/below
            fallbackPlacements={['left-end']}
            padded={false}
            overlay={
                <div className="w-64">
                    {showIncomplete && (
                        <div className="px-3 py-2.5">
                            <LemonSwitch
                                fullWidth
                                label="Incomplete period"
                                checked={exclusions.incomplete}
                                onChange={(incomplete) => onChange({ ...exclusions, incomplete })}
                                data-attr="date-filter-exclude-incomplete-periods"
                            />
                        </div>
                    )}
                    {showIncomplete && showDays && <LemonDivider className="my-0" />}
                    {showDays && (
                        <div className="flex flex-col gap-2 px-3 py-2.5">
                            <div className="flex gap-1">
                                {DAYS_OF_WEEK.map(({ day, label, name }) => {
                                    const selected = exclusions.days.includes(day)
                                    return (
                                        <LemonButton
                                            key={day}
                                            size="xsmall"
                                            type="secondary"
                                            center
                                            className={clsx(
                                                'flex-1',
                                                selected && 'border-accent bg-accent-highlight-secondary text-accent'
                                            )}
                                            onClick={() =>
                                                onChange({
                                                    ...exclusions,
                                                    days: selected
                                                        ? exclusions.days.filter((d) => d !== day)
                                                        : [...exclusions.days, day],
                                                })
                                            }
                                            tooltip={name}
                                            aria-label={`Exclude ${name}`}
                                            aria-pressed={selected}
                                        >
                                            {label}
                                        </LemonButton>
                                    )
                                })}
                            </div>
                            <div className="flex items-center justify-center gap-3">
                                <LemonButton
                                    size="xsmall"
                                    onClick={() => onChange({ ...exclusions, days: ['6', '7'] })}
                                >
                                    Weekends
                                </LemonButton>
                                <LemonButton
                                    size="xsmall"
                                    onClick={() => onChange({ ...exclusions, days: ['1', '2', '3', '4', '5'] })}
                                >
                                    Weekdays
                                </LemonButton>
                                <LemonButton size="xsmall" onClick={() => onChange({ ...exclusions, days: [] })}>
                                    Clear
                                </LemonButton>
                            </div>
                        </div>
                    )}
                </div>
            }
        >
            <LemonButton
                fullWidth
                onClick={() => setVisible(!visible)}
                active={visible}
                size={size}
                sideIcon={<IconChevronRight />}
                data-attr="date-filter-exclusions"
            >
                {summary || 'Exclude'}
            </LemonButton>
        </Popover>
    )
}
