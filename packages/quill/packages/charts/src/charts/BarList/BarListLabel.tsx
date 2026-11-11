import React from 'react'

import type { Series } from '../../core/types'

export interface BarListLabelProps<Meta> {
    series: Series<Meta>
    renderLabel?: (series: Series<Meta>) => React.ReactNode
}

export function BarListLabel<Meta>({ series, renderLabel }: BarListLabelProps<Meta>): React.ReactElement {
    return (
        <span className="flex min-w-0 items-center gap-1.5" title={series.label}>
            {renderLabel ? renderLabel(series) : <span className="truncate">{series.label}</span>}
        </span>
    )
}
