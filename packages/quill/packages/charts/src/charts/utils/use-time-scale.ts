import { useMemo } from 'react'

import type { TimeScale } from '../../core/types'
import { buildTimeTickLabels, inferTimeInterval } from '../../utils/dates'
import { parseDateInTimezone } from '../../utils/dayjs'
import type { XAxisConfig } from '../../utils/use-axis-formatters'

export interface TimeScaleResult {
    timeScale: TimeScale
    tickLabels: string[]
}

export function useTimeScale(
    enabled: boolean,
    labels: string[],
    xAxis: XAxisConfig | undefined,
    xDomain: readonly [number, number] | undefined
): TimeScaleResult | undefined {
    const timezone = xAxis?.timezone ?? 'UTC'
    const interval = xAxis?.interval
    const [domainFrom, domainTo] = xDomain ?? []
    return useMemo(() => {
        if (!enabled) {
            return undefined
        }
        // The shared parse cache clears past 5,000 labels, so a long series would re-parse on every draw.
        const epochs = new Map(labels.map((label) => [label, parseDateInTimezone(label, timezone).valueOf()]))
        const parse = (label: string): number => epochs.get(label) ?? parseDateInTimezone(label, timezone).valueOf()
        const domain: [number, number] =
            domainFrom != null && domainTo != null ? [domainFrom, domainTo] : timeExtent(epochs.values())
        const tickInterval = interval ?? inferTimeInterval(labels, timezone) ?? 'day'
        const grid = buildTimeTickLabels(domain[0], domain[1], tickInterval, timezone)
        return { timeScale: { parse, domain }, tickLabels: grid.length > 0 ? grid : labels }
    }, [enabled, labels, timezone, interval, domainFrom, domainTo])
}

function timeExtent(times: Iterable<number>): [number, number] {
    let from = Infinity
    let to = -Infinity
    for (const t of times) {
        if (isFinite(t)) {
            from = Math.min(from, t)
            to = Math.max(to, t)
        }
    }
    return from <= to ? [from, to] : [NaN, NaN]
}
