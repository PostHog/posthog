import { dayjs } from 'lib/dayjs'

import { Node } from '~/queries/schema/schema-general'
import { AccessControlLevel, InsightShortId, UserBasicType, UserType } from '~/types'

import type { SavedInsightListItem } from './savedInsightsLogic'

/** An insight draft persisted by the insight editor in localStorage under `draft-query-${teamId}`. */
export interface DraftInsightQuery {
    query: Node<Record<string, any>>
    timestamp: number
}

/** Sentinel id for the local draft row in the saved insights table. Real insight ids are positive. */
export const DRAFT_INSIGHT_ROW_ID = -1

/** Storage can hold anything — a non-numeric timestamp would throw in draftInsightListItem and crash the list. */
export function isValidDraftInsightQuery(value: unknown): value is DraftInsightQuery {
    const draft = value as DraftInsightQuery | null
    return (
        !!draft &&
        typeof draft === 'object' &&
        !!draft.query &&
        typeof draft.query === 'object' &&
        typeof draft.query.kind === 'string' &&
        typeof draft.timestamp === 'number' &&
        Number.isFinite(draft.timestamp)
    )
}

export function isDraftInsightRow(item: SavedInsightListItem): boolean {
    return item.id === DRAFT_INSIGHT_ROW_ID
}

/** Shapes the local draft like a saved insight so it can sit in the saved insights table. */
export function draftInsightListItem(draft: DraftInsightQuery, currentUser: UserType | null): SavedInsightListItem {
    const timestamp = dayjs(draft.timestamp).toISOString()
    // UserType is not assignable to UserBasicType (hedgehog_config shapes differ), so pick the basic fields
    const user: UserBasicType | null = currentUser
        ? {
              id: currentUser.id,
              uuid: currentUser.uuid,
              distinct_id: currentUser.distinct_id,
              first_name: currentUser.first_name,
              last_name: currentUser.last_name,
              email: currentUser.email,
          }
        : null
    return {
        id: DRAFT_INSIGHT_ROW_ID,
        // Never used for API calls or links: render paths guard via isDraftInsightRow
        short_id: 'draft' as InsightShortId,
        name: '',
        query: draft.query,
        order: null,
        result: null,
        deleted: false,
        saved: false,
        is_sample: false,
        dashboards: null,
        dashboard_tiles: null,
        last_refresh: null,
        created_at: timestamp,
        created_by: user,
        updated_at: timestamp,
        last_modified_at: timestamp,
        last_modified_by: user,
        last_viewed_at: null,
        tags: [],
        favorited: false,
        user_access_level: AccessControlLevel.Viewer,
    }
}
