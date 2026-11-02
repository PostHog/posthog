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
        const parse = (label: string): number => parseDateInTimezone(label, timezone).valueOf()
        const domain: [number, number] =
            domainFrom != null && domainTo != null ? [domainFrom, domainTo] : labelTimeExtent(labels, parse)
        const tickInterval = interval ?? inferTimeInterval(labels, timezone) ?? 'day'
        return {
            timeScale: { parse, domain },
            tickLabels: buildTimeTickLabels(domain[0], domain[1], tickInterval, timezone),
        }
    }, [enabled, labels, timezone, interval, domainFrom, domainTo])
}

function labelTimeExtent(labels: string[], parse: (label: string) => number): [number, number] {
    let from = Infinity
    let to = -Infinity
    for (const label of labels) {
        const t = parse(label)
        if (isFinite(t)) {
            from = Math.min(from, t)
            to = Math.max(to, t)
        }
    }
    return from <= to ? [from, to] : [NaN, NaN]
}
