import { PropertyOperator, RecordingDurationFilter } from '~/types'
import { OperatorSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { DurationPicker, convertSecondsToDuration } from 'lib/components/DurationPicker/DurationPicker'
import { LemonButton } from '@posthog/lemon-ui'
import { useMemo, useState } from 'react'

interface Props {
    filter: RecordingDurationFilter
    onChange: (value: RecordingDurationFilter) => void
    pageKey: string
}

export const humanFriendlyDurationFilter = (filter: RecordingDurationFilter): string => {
    const operator = filter.operator === PropertyOperator.GreaterThan ? '>' : '<'
    const duration = convertSecondsToDuration(filter.value || 0)
    const unit = duration.timeValue === 1 ? duration.unit.slice(0, -1) : duration.unit
    return `${operator} ${duration.timeValue || 0} ${unit}`
}

export function DurationFilter({ filter, onChange }: Props): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const durationString = useMemo(() => humanFriendlyDurationFilter(filter), [filter])

    return (
        <Popover
            visible={isOpen}
            placement={'bottom-end'}
            fallbackPlacements={['bottom-start']}
            onClickOutside={() => setIsOpen(false)}
            overlay={
                <div className="flex gap-2">
                    <OperatorSelect
                        operator={filter.operator}
                        operators={[PropertyOperator.GreaterThan, PropertyOperator.LessThan]}
                        onChange={(newOperator) => onChange({ ...filter, operator: newOperator })}
                        className="flex-1"
                    />
                    <DurationPicker
                        onChange={(newValue) => onChange({ ...filter, value: newValue })}
                        value={filter.value || undefined}
                    />
                </div>
            }
        >
            <LemonButton
                type="secondary"
                status="stealth"
                size="small"
                onClick={() => {
                    setIsOpen(true)
                }}
            >
                {durationString}
            </LemonButton>
        </Popover>
    )
}
