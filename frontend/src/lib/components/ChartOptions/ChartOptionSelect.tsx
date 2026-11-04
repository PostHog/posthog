import { useId } from 'react'

import { LemonSelect } from '@posthog/lemon-ui'

import { ChartOptionLabel } from './ChartOptionLabel'

export interface ChartOptionChoice<T extends string | number> {
    value: T
    label: string
}

export interface ChartOptionSelectProps<T extends string | number> {
    /** Without a label the select fills the row, for a group whose heading already names it. */
    label?: string
    info?: string
    value: T
    options: ChartOptionChoice<T>[]
    onChange: (value: T) => void
    disabledReason?: string | null
    'data-attr'?: string
}

export function ChartOptionSelect<T extends string | number>(props: ChartOptionSelectProps<T>): JSX.Element {
    const id = useId()

    const { label, info, value, options, onChange, disabledReason, 'data-attr': dataAttr } = props
    const select = (
        <LemonSelect<T>
            id={id}
            size="small"
            fullWidth={!label}
            value={value}
            options={options}
            onChange={onChange}
            disabledReason={disabledReason ?? undefined}
            data-attr={dataAttr}
        />
    )

    if (!label) {
        return select
    }

    return (
        <div className="flex items-center justify-between gap-2">
            <ChartOptionLabel label={label} info={info} htmlFor={id} />
            {select}
        </div>
    )
}
