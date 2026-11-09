import { useId } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { ChartOptionLabel } from './ChartOptionLabel'
import { parseChartOptionNumber, useChartOptionNumberDraft } from './useChartOptionNumberDraft'

export interface ChartOptionNumberInputProps {
    label: string
    info?: string
    value: number | undefined
    onChange: (value: number | undefined) => void
    min?: number
    max?: number
    suffix?: string
    placeholder?: string
    disabledReason?: string | null
    'data-attr'?: string
}

export function ChartOptionNumberInput(props: ChartOptionNumberInputProps): JSX.Element {
    const id = useId()
    const { draft, setDraft, commit } = useChartOptionNumberDraft(props.value, props.onChange)

    const { label, info, min, max, suffix, placeholder, disabledReason, 'data-attr': dataAttr } = props
    return (
        <div className="flex items-center justify-between gap-2">
            <ChartOptionLabel label={label} info={info} htmlFor={id} />
            <LemonInput
                id={id}
                type="number"
                size="small"
                className="w-24"
                value={parseChartOptionNumber(draft)}
                min={min}
                max={max}
                step={1}
                placeholder={placeholder}
                suffix={suffix ? <span>{suffix}</span> : undefined}
                disabledReason={disabledReason ?? undefined}
                onChange={(next) => setDraft(next === undefined ? '' : String(next))}
                onBlur={commit}
                onPressEnter={commit}
                data-attr={dataAttr}
            />
        </div>
    )
}
