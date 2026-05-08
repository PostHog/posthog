import { useMemo } from 'react'

import type { Series } from '../../core/types'

export interface ValueLabelsConfig {
    /** Restricts the labels to these series keys. Series outside the set keep rendering
     *  but have `visibility.valueLabel` flipped off so the {@link ValueLabels} overlay
     *  skips them. Omit (or pass `undefined`) to label every series. */
    seriesKeys?: string[]
    /** Custom value formatter. Falls back to the chart's resolved y-axis formatter when omitted. */
    formatter?: (value: number) => string
}

/** Normalizes the public `valueLabels` prop to a config (or `null` when value labels
 *  are disabled). `true` becomes `{}` so callers can opt in without supplying options. */
export function resolveValueLabelsConfig(
    input: boolean | ValueLabelsConfig | undefined
): ValueLabelsConfig | null {
    if (input === undefined || input === false) {
        return null
    }
    if (input === true) {
        return {}
    }
    return input
}

/** Restrict value-label visibility to a given series-key allowlist. Returns the input
 *  series untouched when no allowlist is set. */
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
