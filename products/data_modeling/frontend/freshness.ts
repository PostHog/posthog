import { DataModelingNode, DataModelingSyncInterval } from '~/types'

export const SYNC_INTERVAL_SECONDS: Record<DataModelingSyncInterval, number> = {
    '15min': 900,
    '30min': 1800,
    '1hour': 3600,
    '6hour': 21600,
    '12hour': 43200,
    '24hour': 86400,
    '7day': 604800,
    '30day': 2592000,
}

/** A plain view runs its query on read, so it stores nothing that can go stale. */
const MATERIALIZING_TYPES = new Set(['matview', 'endpoint'])

/**
 * Age climbs to a full interval between every pair of runs, so a one-interval bar would
 * flag the whole fleet just before each tick. Two means a scheduled run went missing.
 */
export const BEHIND_MULTIPLIER = 2

export interface BehindScheduleModel {
    node: DataModelingNode
    intervalSeconds: number
    /** Seconds since the last successful run, or since creation when it has never finished one. */
    ageSeconds: number
    /** How far past the target the model has drifted. This is the number the table shows. */
    overdueSeconds: number
}

/**
 * Models whose stored data is older than the refresh target they declare. Clearing a
 * target pauses a model on purpose, so a model without one is never behind.
 */
export function modelsBehindSchedule(nodes: DataModelingNode[], now: number): BehindScheduleModel[] {
    const behind: BehindScheduleModel[] = []

    for (const node of nodes) {
        if (!node.sync_interval || !MATERIALIZING_TYPES.has(node.type)) {
            continue
        }
        const intervalSeconds = SYNC_INTERVAL_SECONDS[node.sync_interval]
        if (!intervalSeconds) {
            continue
        }
        // A model that has never run is measured from its creation, so a new one is not
        // reported before its first tick was even due.
        const since = node.last_run_at ?? node.created_at
        const ageSeconds = (now - new Date(since).getTime()) / 1000
        if (ageSeconds <= intervalSeconds * BEHIND_MULTIPLIER) {
            continue
        }
        behind.push({ node, intervalSeconds, ageSeconds, overdueSeconds: ageSeconds - intervalSeconds })
    }

    return behind.sort((a, b) => b.overdueSeconds - a.overdueSeconds)
}
