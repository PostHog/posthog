export interface BillingSeriesKeySource {
    label: string
    breakdown_value?: string | string[] | null
}

export function billingSeriesKey(series: BillingSeriesKeySource): string {
    const value = series.breakdown_value
    const hasValue = Array.isArray(value) ? value.length > 0 : value != null && value !== ''
    return hasValue ? JSON.stringify(value) : series.label
}

export function withSeriesKey<T extends BillingSeriesKeySource>(series: T): T & { key: string } {
    return { ...series, key: billingSeriesKey(series) }
}

interface KeyedSeries {
    key: string
    data: number[]
}

const total = (series: KeyedSeries): number => series.data.reduce((sum, value) => sum + value, 0)

export function emptySeriesKeys(series: KeyedSeries[]): string[] {
    return series.filter((s) => total(s) === 0).map((s) => s.key)
}

export function hiddenSeriesForDisplay(userHidden: string[], excludeEmpty: boolean, emptyKeys: string[]): string[] {
    return excludeEmpty ? Array.from(new Set([...userHidden, ...emptyKeys])) : userHidden
}

// The header checkbox hides every series that could be shown, or shows them all again. Hidden keys
// with no series in the current response are kept, so they still apply when that series comes back.
export function hiddenSeriesAfterToggleAll(
    series: KeyedSeries[],
    excludeEmpty: boolean,
    userHidden: string[]
): string[] {
    const keys = (excludeEmpty ? series.filter((s) => total(s) > 0) : series).map((s) => s.key)
    const hidden = new Set(userHidden)
    const allVisible = keys.length > 0 && keys.every((key) => !hidden.has(key))
    return allVisible ? Array.from(new Set([...userHidden, ...keys])) : []
}
