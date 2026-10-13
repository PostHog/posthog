import { useEffect, useState } from 'react'

import { Slider, Text } from '@posthog/quill'

import type { ParamSpec } from '../../../editing/blockLibrary/params'

function stepOf(spec: ParamSpec): number {
    if (spec.step !== null) {
        return spec.step
    }
    const range = (spec.max ?? 1) - (spec.min ?? 0)
    return Number.isInteger(spec.min) && Number.isInteger(spec.max) && range >= 2 ? 1 : range / 100
}

function firstValue(next: number | readonly number[]): number | undefined {
    return Array.isArray(next) ? next[0] : (next as number)
}

/** A bounded number param. The source changes when the author lets go, not while they drag. */
export function ParamSlider({
    value,
    spec,
    onCommit,
}: {
    value: number
    spec: ParamSpec
    onCommit: (value: number) => void
}): JSX.Element {
    const [draft, setDraft] = useState(value)
    useEffect(() => setDraft(value), [value])
    const step = stepOf(spec)
    const decimals = step < 1 ? Math.min(2, String(step).split('.')[1]?.length ?? 1) : 0
    return (
        <div className="flex items-center gap-3">
            <Slider
                aria-label={spec.label}
                value={[draft]}
                min={spec.min ?? 0}
                max={spec.max ?? 100}
                step={step}
                className="min-w-0 flex-1"
                onValueChange={(next: number | readonly number[]) => {
                    const raw = firstValue(next)
                    if (typeof raw === 'number') {
                        setDraft(raw)
                    }
                }}
                onValueCommitted={(next: number | readonly number[]) => {
                    const raw = firstValue(next)
                    if (typeof raw === 'number') {
                        const rounded = Number(raw.toFixed(decimals))
                        if (rounded !== value) {
                            onCommit(rounded)
                        }
                    }
                }}
            />
            <Text
                size="xs"
                variant="muted"
                render={<span />}
                className="w-9 shrink-0 text-right tabular-nums"
                translate="no"
            >
                {draft.toFixed(decimals)}
            </Text>
        </div>
    )
}
