import { apiMutator } from 'lib/api-orval-mutator'
import { toParams } from 'lib/utils/url'

import { NodeKind, type RecordingsQuery, type RecordingsQueryResponse } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { getSessionRecordingsListUrl } from 'products/replay/frontend/generated/api'

import { getTileRecord, type AccountViewTileConfig } from './accountViewTileConfig'

export const ACCOUNT_REPLAYS_PAGE_SIZE = 20

export interface AccountReplayDateRange {
    date_from: string | null
    date_to: string | null
}

export function getAccountReplayDateRange(config?: AccountViewTileConfig): AccountReplayDateRange {
    const dateRange = getTileRecord(config, 'dateRange')
    return {
        date_from:
            typeof dateRange?.date_from === 'string' || dateRange?.date_from === null ? dateRange.date_from : '-7d',
        date_to: typeof dateRange?.date_to === 'string' ? dateRange.date_to : null,
    }
}

export function createAccountReplayQuery(
    externalId: string,
    groupTypeIndex: number | null | undefined,
    dateRange: AccountReplayDateRange,
    personUUID: string | null,
    page?: { cursor?: string; offset: number }
): RecordingsQuery | null {
    if (
        !externalId.trim() ||
        !Number.isInteger(groupTypeIndex) ||
        groupTypeIndex == null ||
        groupTypeIndex < 0 ||
        groupTypeIndex > 4
    ) {
        return null
    }
    return {
        kind: NodeKind.RecordingsQuery,
        ...dateRange,
        date_from: dateRange.date_from ?? 'all',
        properties: [
            {
                key: `$group_${groupTypeIndex}`,
                type: PropertyFilterType.Event,
                operator: PropertyOperator.Exact,
                value: [externalId],
            },
        ],
        event_match_scope: 'session',
        person_uuid: personUUID ?? undefined,
        order: 'start_time',
        order_direction: 'DESC',
        limit: ACCOUNT_REPLAYS_PAGE_SIZE,
        // An explicit offset disables replay cursor pagination, including offset zero.
        ...(page?.cursor ? { after: page.cursor } : page ? { offset: page.offset } : {}),
    }
}

export async function getAccountReplayRecordings(
    projectId: number,
    query: RecordingsQuery
): Promise<RecordingsQueryResponse> {
    // The generated list response describes Django pagination, but replay returns the RecordingsQuery cursor envelope.
    // Keep the generated route and the shared query schema instead of copying that contract or changing the replay API.
    const url = `${getSessionRecordingsListUrl(String(projectId))}?${toParams(query)}`
    return apiMutator<RecordingsQueryResponse>(url, { method: 'GET' })
}
