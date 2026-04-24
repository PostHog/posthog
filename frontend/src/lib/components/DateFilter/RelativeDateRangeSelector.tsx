import { useState } from 'react'

import { LemonButton, LemonDivider, LemonInput, LemonSelect } from '@posthog/lemon-ui'

interface RelativeDateRangeSelectorProps {
    onApply: (dateFrom: string, dateTo: string) => void
    onClose: () => void
}

const UNIT_OPTIONS: { value: string; label: string }[] = [
    { value: 'd', label: 'days' },
    { value: 'w', label: 'weeks' },
    { value: 'm', label: 'months' },
    { value: 'y', label: 'years' },
]

// Approximate day multipliers used only to validate that the "from" offset is
// strictly further in the past than the "to" offset before the user applies.
const UNIT_TO_DAYS: Record<string, number> = { d: 1, w: 7, m: 30, y: 365 }

function offsetInDays(value: string, unit: string): number {
    const n = Number.parseInt(value, 10)
    if (Number.isNaN(n) || n <= 0) {
        return NaN
    }
    return n * (UNIT_TO_DAYS[unit] ?? 1)
}

export function RelativeDateRangeSelector({ onApply, onClose }: RelativeDateRangeSelectorProps): JSX.Element {
    const [fromValue, setFromValue] = useState<string>('30')
    const [fromUnit, setFromUnit] = useState<string>('d')
    const [toValue, setToValue] = useState<string>('7')
    const [toUnit, setToUnit] = useState<string>('d')

    const fromDays = offsetInDays(fromValue, fromUnit)
    const toDays = offsetInDays(toValue, toUnit)
    const isValid = !Number.isNaN(fromDays) && !Number.isNaN(toDays) && fromDays > toDays

    const handleApply = (): void => {
        if (!isValid) {
            return
        }
        onApply(`-${fromValue}${fromUnit}`, `-${toValue}${toUnit}`)
    }

    return (
        <div className="min-w-60">
            <div className="p-2 deprecated-space-y-2">
                <div className="text-sm font-medium">Custom relative range</div>

                <div className="deprecated-space-y-3">
                    <div className="flex items-center gap-2">
                        <span className="text-sm text-muted-alt min-w-12">From:</span>
                        <LemonInput
                            type="number"
                            value={Number.parseInt(fromValue, 10) || undefined}
                            onChange={(value) => setFromValue(String(value ?? ''))}
                            placeholder="30"
                            className="w-20"
                            min={1}
                        />
                        <LemonSelect value={fromUnit} onChange={(v) => v && setFromUnit(v)} options={UNIT_OPTIONS} />
                        <span className="text-sm text-muted-alt">ago</span>
                    </div>

                    <div className="flex items-center gap-2">
                        <span className="text-sm text-muted-alt min-w-12">To:</span>
                        <LemonInput
                            type="number"
                            value={Number.parseInt(toValue, 10) || undefined}
                            onChange={(value) => setToValue(String(value ?? ''))}
                            placeholder="7"
                            className="w-20"
                            min={1}
                        />
                        <LemonSelect value={toUnit} onChange={(v) => v && setToUnit(v)} options={UNIT_OPTIONS} />
                        <span className="text-sm text-muted-alt">ago</span>
                    </div>
                </div>

                {!isValid ? (
                    <div className="text-xs text-danger">"From" must be further in the past than "To".</div>
                ) : (
                    <div className="text-xs text-muted-alt">Example: from 30 days ago to 7 days ago</div>
                )}
            </div>

            <LemonDivider />

            <div className="p-2 flex justify-end gap-2">
                <LemonButton type="secondary" size="small" onClick={onClose}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={handleApply}
                    disabledReason={isValid ? undefined : 'Adjust the range to apply'}
                >
                    Apply
                </LemonButton>
            </div>
        </div>
    )
}
