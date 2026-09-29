import type {
    AiObservabilityOfflineExperimentsListParams,
    AiObservabilityOfflineScorersHistoryListParams,
} from '../generated/api.schemas'

export type OfflineExperimentFilters = Pick<
    AiObservabilityOfflineExperimentsListParams,
    'search' | 'statuses' | 'run_source' | 'date_from' | 'date_to'
>

export type OfflineOverviewTrendFilters = Pick<
    AiObservabilityOfflineScorersHistoryListParams,
    'run_source' | 'statuses'
>

export const OFFLINE_ALL_UPLOAD_STATES = 'completed,uploading,failed'
const FILTER_KEYS = ['search', 'statuses', 'run_source', 'date_from', 'date_to'] as const
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

export function parseOfflineScorerIds(value: unknown): string[] | null {
    if (!Array.isArray(value) || !value.every((id) => typeof id === 'string' && UUID_PATTERN.test(id))) {
        return null
    }
    return [...new Set(value.map((id: string) => id.toLowerCase()))]
}

export function offlinePreferencesKey(userId: number, teamId: number): string {
    // This key is persisted in browsers; keep its identity stable across UI renames.
    return `aio-offline-overview:v1:${userId}:${teamId}`
}

export function readOfflineScorerPreferences(userId: number, teamId: number): string[] | null {
    try {
        const raw = localStorage.getItem(offlinePreferencesKey(userId, teamId))
        const stored: unknown = raw ? JSON.parse(raw) : null
        if (
            typeof stored !== 'object' ||
            stored === null ||
            !('version' in stored) ||
            stored.version !== 1 ||
            !('scorerIds' in stored)
        ) {
            return null
        }
        return parseOfflineScorerIds(stored.scorerIds)
    } catch {
        return null
    }
}

export function saveOfflineScorerPreferences(userId: number, teamId: number, scorerIds: string[]): void {
    try {
        localStorage.setItem(offlinePreferencesKey(userId, teamId), JSON.stringify({ version: 1, scorerIds }))
    } catch {
        // Browser storage can be disabled; the active selection remains usable in memory.
    }
}

export function offlineFiltersFromUrl(search: Record<string, unknown>): OfflineExperimentFilters {
    // Keep shared links from the separate trend controls usable with the unified filters.
    const shared: Record<string, unknown> = {
        ...search,
        date_from: search.date_from ?? search.trend_from,
        date_to: search.date_to ?? search.trend_to,
        run_source: search.run_source ?? search.trend_run_source,
    }
    return Object.fromEntries(
        FILTER_KEYS.flatMap((key) => {
            const raw = shared[key]
            const value = key === 'search' && Array.isArray(raw) && raw.length === 1 ? raw[0] : raw
            return typeof value === 'string' && value ? [[key, value]] : []
        })
    )
}

export function offlineFiltersToUrl(filters: OfflineExperimentFilters): Record<string, unknown> {
    // The router decodes text such as "00123" or "true" as a number or boolean, but it keeps a JSON array exactly.
    return { ...filters, search: filters.search ? [filters.search] : undefined }
}

export function offlineListClockFromUrl(search: Record<string, unknown>): string | null {
    return typeof search.list_now === 'string' && !Number.isNaN(Date.parse(search.list_now))
        ? new Date(search.list_now).toISOString()
        : null
}

export function offlineCursorStackFromUrl(search: Record<string, unknown>): string[] {
    if (!offlineListClockFromUrl(search)) {
        return []
    }
    const stack = search.cursor_stack
    return Array.isArray(stack) && stack.every((cursor) => typeof cursor === 'string' && cursor.length > 0) ? stack : []
}

export function cleanOfflineFilters(filters: OfflineExperimentFilters): OfflineExperimentFilters {
    return offlineFiltersFromUrl(filters)
}

export function offlineRunSourceLabel(source: string | null): string {
    return source === 'ci'
        ? 'CI'
        : source === 'local'
          ? 'Local'
          : source === 'scheduled'
            ? 'Scheduled'
            : 'Not specified'
}

// A page can contain many chosen charts; keep their independent reads bounded.
let activeTrendReads = 0
const waitingTrendReads: (() => void)[] = []

export async function withOfflineTrendReadLimit<T>(read: () => Promise<T>): Promise<T> {
    if (activeTrendReads >= 3) {
        await new Promise<void>((resolve) => waitingTrendReads.push(resolve))
    } else {
        activeTrendReads++
    }
    try {
        return await read()
    } finally {
        const next = waitingTrendReads.shift()
        if (next) {
            next()
        } else {
            activeTrendReads--
        }
    }
}
