import { useMemo } from 'react'

import type { TimeScale } from '../../core/types'
import { parseDateInTimezone } from '../../utils/dayjs'

export function useTimeScale(
    enabled: boolean,
    labels: string[],
    timezone: string,
    xDomain: readonly [number, number] | undefined
): TimeScale | undefined {
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
        return { parse, domain }
    }, [enabled, labels, timezone, domainFrom, domainTo])
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
