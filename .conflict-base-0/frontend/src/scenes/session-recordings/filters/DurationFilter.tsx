import { useMemo, useState } from 'react'

import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'

import { DurationPicker, convertSecondsToDuration } from 'lib/components/DurationPicker/DurationPicker'
import { OperatorSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { DurationTypeSelect } from 'scenes/session-recordings/filters/DurationTypeSelect'

import { DurationType, PropertyOperator, RecordingDurationFilter } from '~/types'

interface DurationFilterProps {
    recordingDurationFilter: RecordingDurationFilter
    durationTypeFilter: DurationType
    onChange: (recordingDurationFilter: RecordingDurationFilter, durationType: DurationType) => void
    pageKey: string
    size?: LemonButtonProps['size']
    type?: LemonButtonProps['type']
}

const durationTypeMapping: Record<DurationType, string> = {
    duration: '',
    active_seconds: 'active ',
    inactive_seconds: 'inactive ',
}

export const humanFriendlyDurationFilter = (
    recordingDurationFilter: RecordingDurationFilter,
    durationTypeFilter: DurationType
): string => {
    const operator = recordingDurationFilter.operator === PropertyOperator.GreaterThan ? '>' : '<'
    const duration = convertSecondsToDuration(recordingDurationFilter.value || 0)
    const durationDescription = durationTypeMapping[durationTypeFilter]
    const unit = duration.timeValue === 1 ? duration.unit.slice(0, -1) : duration.unit
    return `${operator} ${duration.timeValue || 0} ${durationDescription}${unit}`
}

export function DurationFilter({
    recordingDurationFilter,
    durationTypeFilter,
    onChange,
    size,
    type,
}: DurationFilterProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const durationString = useMemo(
        () => humanFriendlyDurationFilter(recordingDurationFilter, durationTypeFilter),
        [recordingDurationFilter, durationTypeFilter]
    )

    return (
        <Popover
            visible={isOpen}
            placement="bottom-start"
            fallbackPlacements={['bottom-end']}
            onClickOutside={() => setIsOpen(false)}
            overlay={
                <div className="flex gap-2">
                    <OperatorSelect
                        operator={recordingDurationFilter.operator}
                        operators={[PropertyOperator.GreaterThan, PropertyOperator.LessThan]}
                        onChange={(newOperator) =>
                            onChange({ ...recordingDurationFilter, operator: newOperator }, durationTypeFilter)
                        }
                        className="flex-1"
                    />
                    <DurationPicker
                        onChange={(newValue) =>
                            onChange({ ...recordingDurationFilter, value: newValue }, durationTypeFilter)
                        }
                        value={recordingDurationFilter.value || undefined}
                    />

                    <DurationTypeSelect
                        onChange={(v) => onChange(recordingDurationFilter, v)}
                        value={durationTypeFilter}
                    />
                </div>
            }
        >
            <LemonButton
                type={type ?? 'secondary'}
                size={size ?? 'small'}
                onClick={() => {
                    setIsOpen(true)
                }}
            >
                {durationString}
            </LemonButton>
        </Popover>
    )
}
