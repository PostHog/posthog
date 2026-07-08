import { useMemo } from 'react'

import type { Series } from '../../core/types'
import type { ValueLabelFormatter } from '../../overlays/ValueLabels'

export interface ValueLabelsConfig {
    seriesKeys?: string[]
    /** Per-segment label text — see `ValueLabelFormatter` for the context and empty-string contract. */
    formatter?: ValueLabelFormatter
}

export function resolveValueLabelsConfig(input: boolean | ValueLabelsConfig | undefined): ValueLabelsConfig | null {
    if (input === undefined || input === false) {
        return null
    }
    if (input === true) {
        return {}
    }
    return input
}

export function useSeriesWithValueLabelAllowlist<Meta>(
    series: Series<Meta>[],
    seriesKeys: string[] | undefined
): Series<Meta>[] {
    // Stable primitive key so callers can pass `valueLabels: { seriesKeys: ['a'] }` inline
    // without re-running the transform on every render. JSON.stringify (rather than
    // `join(' ')`) so a key that contains a space doesn't collide with two keys split on
    // it (`['a b']` vs `['a','b']`).
    const seriesKeysSignature = JSON.stringify(seriesKeys ?? null)
    return useMemo(() => {
        if (!seriesKeys) {
            return series
        }
        const allowed = new Set(seriesKeys)
        return series.map((s) =>
            allowed.has(s.key) ? s : { ...s, visibility: { ...s.visibility, valueLabel: false } }
        )
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [series, seriesKeysSignature])
}
