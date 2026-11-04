import type { AssignmentStatus } from 'lib/components/AccountAssignmentFilter/accountAssignmentFilterTypes'

import {
    AccountsTableRelationshipOperator,
    NodeKind,
    type AccountsTableQuery,
    type AccountsTableRow,
    type DateRange,
    type HogQLQuery,
} from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from '../../constants'
import { getMatrixHogQLScope } from '../Accounts/dotMatrixHogQLScope'

export const BOOK_ACCOUNT_LIMIT = 200
export interface ProductUsageFilters {
    search: string
    assignedTo: number[]
    assignmentStatus: AssignmentStatus
    relationshipId: string | null
}
export function buildProductUsageAccountsQuery(filters: ProductUsageFilters): AccountsTableQuery {
    return {
        kind: NodeKind.AccountsTableQuery,
        columns: [],
        useDefaultColumns: false,
        limit: BOOK_ACCOUNT_LIMIT,
        offset: 0,
        filters: [
            ...(filters.search.trim() ? [{ kind: 'search' as const, query: filters.search.trim() }] : []),
            ...(filters.assignmentStatus === 'all' ? [] : [{ kind: filters.assignmentStatus }]),
            ...(filters.relationshipId
                ? [
                      {
                          kind: 'relationship' as const,
                          definitionId: filters.relationshipId,
                          operator: filters.assignedTo.length
                              ? AccountsTableRelationshipOperator.Exact
                              : AccountsTableRelationshipOperator.IsSet,
                          ...(filters.assignedTo.length ? { userIds: filters.assignedTo } : {}),
                      },
                  ]
                : filters.assignedTo.length
                  ? [{ kind: 'assigned_to' as const, userIds: filters.assignedTo }]
                  : []),
        ],
        tags: { ...CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS, name: 'customer_analytics_product_activity_accounts' },
    }
}
export function buildProductUsageHogQLQuery(
    query: string,
    accounts: AccountsTableRow[],
    dateRange: DateRange,
    groupTypeIndex?: number | null
): HogQLQuery {
    const externalIds = accounts.flatMap((account) => (account.externalId ? [account.externalId] : []))
    if (getMatrixHogQLScope(query).usesFilters && groupTypeIndex == null) {
        throw Object.assign(
            new Error('Choose an account group type in Customer analytics settings to use {filters}.'),
            { status: 400 }
        )
    }
    if (getMatrixHogQLScope(query).usesFilters && !externalIds.length) {
        throw Object.assign(
            new Error('No filtered account is linked to activity. Link an account or choose different filters.'),
            { status: 400 }
        )
    }
    return {
        kind: NodeKind.HogQLQuery,
        query,
        values: { account_ids: accounts.map(({ id }) => id), account_external_ids: externalIds },
        filters: {
            dateRange,
            properties:
                groupTypeIndex == null
                    ? []
                    : [
                          {
                              type: PropertyFilterType.Event,
                              key: `$group_${groupTypeIndex}`,
                              operator: PropertyOperator.Exact,
                              value: externalIds,
                          },
                      ],
        },
        tags: { ...CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS, name: 'customer_analytics_product_activity_hogql' },
    }
}
export function productUsageStarterQuery(groupTypeIndex: number | null | undefined): string {
    const group = groupTypeIndex == null ? 0 : groupTypeIndex
    return `SELECT
    properties.$group_${group} AS row,
    toString(toStartOfInterval(timestamp, INTERVAL 1 WEEK)) AS column,
    event AS series,
    person_id AS user
FROM events
WHERE {filters}
GROUP BY row, column, series, user
ORDER BY column DESC, row, series
LIMIT 10000`
}
