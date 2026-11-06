import { performQuery } from '~/queries/query'
import {
    NodeKind,
    type AccountActivityMatrixResult,
    type AccountActivityMatrixQuery,
    type BookActivityMatrixQuery,
    type BookActivityMatrixResult,
    type HogQLQuery,
    type HogQLQueryResponse,
} from '~/queries/schema/schema-general'

import { CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from '../../constants'
import { getActivityHogQLBindings } from '../ProductActivity/activityHogQLBindings'
import type { DotMatrixTileSource, DotMatrixWeeks } from '../ProductActivity/dotMatrixTileConfig'
import { getMatrixHogQLScope } from './dotMatrixHogQLScope'

export interface DotMatrixQueryContext {
    accountId: string
    externalId?: string
    groupTypeIndex?: number | null
    includeFirstUse?: boolean
    weekStartDay?: number
    weeks: DotMatrixWeeks
}

export type DotMatrixTileResult =
    | { kind: 'usage_metrics'; result: AccountActivityMatrixResult }
    | { kind: 'product_usage'; result: BookActivityMatrixResult }
    | { kind: 'hogql'; query: string; result: HogQLQueryResponse }

export function createMatrixHogQLQuery(query: string, context: DotMatrixQueryContext): HogQLQuery {
    if (getMatrixHogQLScope(query).usesFilters && (context.groupTypeIndex == null || !context.externalId)) {
        // Status 400 marks this as the user's to fix, like a SQL mistake, so it isn't reported as an exception.
        throw Object.assign(
            new Error(
                'Link this account and choose an account group type in Customer analytics settings to use {filters}.'
            ),
            { status: 400 }
        )
    }
    return {
        kind: NodeKind.HogQLQuery,
        tags: { ...CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS, scene: 'CustomerAnalytics' },
        query,
        ...getActivityHogQLBindings(context),
    }
}

export async function queryDotMatrixSource(
    source: DotMatrixTileSource,
    context: DotMatrixQueryContext,
    signal: AbortSignal,
    queryId: string
): Promise<DotMatrixTileResult> {
    switch (source.kind) {
        case 'usage_metrics': {
            const response = await performQuery<AccountActivityMatrixQuery>(
                {
                    kind: NodeKind.AccountActivityMatrixQuery,
                    tags: CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS,
                    accountId: context.accountId,
                    weeks: context.weeks,
                },
                { signal },
                'blocking',
                queryId
            )
            return { kind: source.kind, result: response.results }
        }
        case 'product_usage': {
            const response = await performQuery<BookActivityMatrixQuery>(
                {
                    kind: NodeKind.BookActivityMatrixQuery,
                    tags: CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS,
                    accountIds: [context.accountId],
                    dateRange: { date_from: `-${context.weeks - 1}wStart`, date_to: null },
                    interval: 'week',
                    includeFirstUse: context.includeFirstUse ?? false,
                },
                { signal },
                'blocking',
                queryId
            )
            return { kind: source.kind, result: response.results }
        }
        case 'hogql':
            return {
                kind: source.kind,
                query: source.query,
                result: await performQuery(
                    createMatrixHogQLQuery(source.query, context),
                    { signal },
                    'blocking',
                    queryId
                ),
            }
    }
}
