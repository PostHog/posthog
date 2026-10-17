import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import type { AccountExpansionTab } from './accountsExpansionLogic'

// History points arrive in timestamp order. The Postgres runner sends `{ timestamp, value }`
// objects, and HogQL `AccountsQuery` sends `[unixSeconds, value]` tuples.
export function parseHistoryPoints(raw: unknown): [number, number][] {
    if (!Array.isArray(raw)) {
        return []
    }
    const points: [number, number][] = []
    for (const entry of raw) {
        let timestamp: number
        let value: number
        if (Array.isArray(entry) && entry.length >= 2) {
            timestamp = Number(entry[0])
            value = Number(entry[1])
        } else if (typeof entry === 'object' && entry !== null && 'timestamp' in entry && 'value' in entry) {
            timestamp = Math.floor(Date.parse(String(entry.timestamp)) / 1000)
            value = Number(entry.value)
        } else {
            continue
        }
        if (Number.isFinite(timestamp) && Number.isFinite(value)) {
            points.push([timestamp, value])
        }
    }
    return points
}

export interface HistoryDisplay {
    latest: [number, number] | null
    /** The value in effect at the window start: the last write before the cutoff,
     * carried forward, so sparsely-written properties still chart at any window. */
    baseline: [number, number] | null
    chartPoints: [number, number][]
}

export function buildHistoryDisplay(allPoints: [number, number][], windowDays: number, nowMs: number): HistoryDisplay {
    const cutoff = Math.floor(nowMs / 1000) - windowDays * 24 * 60 * 60
    const inWindow = allPoints.filter(([timestamp]) => timestamp >= cutoff)
    const lastBefore = allPoints.filter(([timestamp]) => timestamp < cutoff).at(-1) ?? null
    const carriedForward: [number, number] | null = lastBefore ? [cutoff, lastBefore[1]] : null
    const latest = inWindow.at(-1) ?? lastBefore
    return {
        latest,
        baseline: carriedForward ?? inWindow[0] ?? null,
        chartPoints: carriedForward ? [carriedForward, ...inWindow] : inWindow,
    }
}

const CANONICAL_PROPERTY_TAB: Record<string, AccountExpansionTab> = {
    'Last Slack message at': 'conversations',
}

export function getCanonicalPropertyTab(definition: CustomPropertyDefinitionApi): AccountExpansionTab | undefined {
    return definition.is_canonical ? CANONICAL_PROPERTY_TAB[definition.name] : undefined
}
