import React from 'react'

import { percentage } from '../../utils/format'
import type { BarListConfig } from './BarList'

export interface BarListValueProps {
    value: number
    whole: number
    valueDisplay: NonNullable<BarListConfig['valueDisplay']>
    labelPosition: NonNullable<BarListConfig['labelPosition']>
    valueFormatter: (value: number) => string
}

function formatShare(fraction: number): string {
    return fraction > 0 && fraction < 0.001 ? '<0.1%' : percentage(fraction, 1)
}

export function BarListValue({
    value,
    whole,
    valueDisplay,
    labelPosition,
    valueFormatter,
}: BarListValueProps): React.ReactElement {
    return (
        <>
            {valueDisplay === 'value' ? valueFormatter(value) : formatShare(whole > 0 ? value / whole : 0)}
            {valueDisplay === 'both' ? (
                <span className={labelPosition === 'start' ? '@max-md:hidden' : undefined}>
                    {' '}
                    · {valueFormatter(value)}
                </span>
            ) : null}
        </>
    )
}
