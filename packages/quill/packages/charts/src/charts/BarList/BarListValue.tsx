import React from 'react'

import { formatShare } from '../../utils/format'
import type { BarListConfig } from './BarList'

export interface BarListValueProps {
    value: number
    whole: number
    valueDisplay: NonNullable<BarListConfig['valueDisplay']>
    labelPosition: NonNullable<BarListConfig['labelPosition']>
    valueFormatter: (value: number) => string
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
