import { HistogramGraphDatum } from '~/types'

export interface TimeToConvertCompareRow extends HistogramGraphDatum {
    /** The matching bin from the previous period, or null outside compare mode / when absent. */
    previous: HistogramGraphDatum | null
}

/** Zips the current and previous time-to-convert bins into one row per bin.
 *
 * Compare-to-previous for time-to-convert is computed on shared bin boundaries, so the two periods
 * align positionally — `previous[i]` is the same duration bucket as `current[i]`. A shorter or
 * missing previous series leaves `previous: null` rather than misaligning the columns. */
export function buildTimeToConvertCompareRows(
    current: HistogramGraphDatum[],
    previous: HistogramGraphDatum[] | null
): TimeToConvertCompareRow[] {
    return current.map((datum, index) => ({
        ...datum,
        previous: previous?.[index] ?? null,
    }))
}
