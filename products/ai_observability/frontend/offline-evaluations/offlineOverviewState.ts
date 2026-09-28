import type {
    AiObservabilityOfflineExperimentsListParams,
    AiObservabilityOfflineScorersHistoryListParams,
} from '../generated/api.schemas'

export type OfflineExperimentFilters = Omit<AiObservabilityOfflineExperimentsListParams, 'cursor' | 'limit'>

export const OFFLINE_TREND_CONTEXT_FILTERS = [
    ['suite_key', 'Suite'],
    ['dataset_source', 'Dataset source'],
    ['dataset_identifier', 'Dataset identifier'],
    ['dataset_revision_identifier', 'Dataset revision'],
] as const

export type OfflineOverviewTrendFilters = Pick<
    AiObservabilityOfflineScorersHistoryListParams,
    'run_source' | (typeof OFFLINE_TREND_CONTEXT_FILTERS)[number][0]
>

const TREND_FILTER_KEYS = ['run_source', ...OFFLINE_TREND_CONTEXT_FILTERS.map(([key]) => key)] as const

export const OFFLINE_CONTEXT_FILTERS = [
    ['suite_key', 'Suite'],
    ['dataset_source', 'Dataset source'],
    ['dataset_identifier', 'Dataset identifier'],
    ['dataset_revision_identifier', 'Dataset revision'],
    ['application_version', 'Application version'],
    ['model_version', 'Model version'],
    ['prompt_version', 'Prompt version'],
    ['scorer_definition_id', 'Scorer definition ID'],
    ['scorer_version_ids', 'Scorer version IDs'],
] as const

const FILTER_KEYS = [
    'search',
    'statuses',
    'run_source',
    'date_from',
    'date_to',
    ...OFFLINE_CONTEXT_FILTERS.map(([key]) => key),
] as const
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
    return Object.fromEntries(
        FILTER_KEYS.flatMap((key) => {
            const value = search[key]
            return typeof value === 'string' && value ? [[key, value]] : []
        })
    )
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

export function offlineTrendFiltersToUrl(filters: OfflineOverviewTrendFilters): Record<string, string> {
    return Object.fromEntries(
        TREND_FILTER_KEYS.flatMap((key) => {
            const value = filters[key]
            return typeof value === 'string' && value ? [[`trend_${key}`, value]] : []
        })
    )
}

export function offlineTrendFiltersFromUrl(search: Record<string, unknown>): OfflineOverviewTrendFilters {
    return Object.fromEntries(
        TREND_FILTER_KEYS.flatMap((key) => {
            const value = search[`trend_${key}`]
            return typeof value === 'string' && value ? [[key, value]] : []
        })
    )
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
