import { actions, kea, path, reducers, selectors } from 'kea'

import { now } from 'lib/dayjs'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import type { recentColumnsLogicType } from './recentColumnsLogicType'

export const MAX_RECENT_COLUMNS_PER_CONTEXT = 12
export const RECENT_COLUMN_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000

export interface RecentColumn {
    column: string
    timestamp: number
}

export type RecentColumnsByContext = Record<string, RecentColumn[]>

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id

export const recentColumnsLogic = kea<recentColumnsLogicType>([
    path(['queries', 'nodes', 'DataTable', 'ColumnConfigurator', 'recentColumnsLogic']),
    actions({
        recordRecentColumn: (contextKey: string, column: string) => ({ contextKey, column }),
        clearRecentColumns: (contextKey: string) => ({ contextKey }),
    }),
    reducers({
        recentColumnsByContext: [
            {} as RecentColumnsByContext,
            { persist: true, prefix: `${teamId}__` },
            {
                clearRecentColumns: (state, { contextKey }) => {
                    if (!(contextKey in state)) {
                        return state
                    }
                    const { [contextKey]: _removed, ...rest } = state
                    return rest
                },
                recordRecentColumn: (state, { contextKey, column }) => {
                    if (!contextKey || !column) {
                        return state
                    }
                    const currentTime = now().valueOf()
                    const cutoff = currentTime - RECENT_COLUMN_MAX_AGE_MS
                    const existing = state[contextKey] ?? []
                    const withoutDuplicate = existing.filter((c) => c.column !== column)
                    const withoutExpired = withoutDuplicate.filter((c) => c.timestamp > cutoff)
                    const next = [{ column, timestamp: currentTime }, ...withoutExpired].slice(
                        0,
                        MAX_RECENT_COLUMNS_PER_CONTEXT
                    )
                    return { ...state, [contextKey]: next }
                },
            },
        ],
    }),
    selectors({
        recentColumnsForContext: [
            (s) => [s.recentColumnsByContext],
            (recentColumnsByContext: RecentColumnsByContext) =>
                (contextKey: string | undefined): string[] => {
                    if (!contextKey) {
                        return []
                    }
                    return (recentColumnsByContext[contextKey] ?? []).map((c) => c.column)
                },
        ],
    }),
    permanentlyMount(),
])
