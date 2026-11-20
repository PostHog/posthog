import { NodeKind, type BookActivityMatrixQuery } from '~/queries/schema/schema-general'

import { CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from '../../constants'
import { ActivityQueryRequest } from '../ProductActivity/activityQueryRequest'
import type { ProductUsageControls } from './productUsageControlValues'
import type { ProductUsageLoadResult, ProductUsageSource } from './productUsageData'
import { buildProductUsageAccountsQuery, buildProductUsageHogQLQuery } from './productUsageQueries'

export async function loadProductUsage(
    request: ActivityQueryRequest,
    source: ProductUsageSource,
    controls: ProductUsageControls,
    groupTypeIndex: number | null | undefined,
    refresh: 'blocking' | 'force_blocking'
): Promise<ProductUsageLoadResult> {
    const accounts = await request.perform(buildProductUsageAccountsQuery(controls), refresh)
    request.throwIfAborted()
    let matrix = null
    let hogql = null
    if (accounts.results.length) {
        if (source.kind === 'product_usage') {
            matrix = (
                await request.perform<BookActivityMatrixQuery>(
                    {
                        kind: NodeKind.BookActivityMatrixQuery,
                        accountIds: accounts.results.map(({ id }) => id),
                        dateRange: controls.dateRange,
                        interval: controls.interval,
                        includeFirstUse: false,
                        rowLimit: 200,
                        tags: CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS,
                    },
                    refresh
                )
            ).results
        } else {
            hogql = await request.perform(
                buildProductUsageHogQLQuery(source.query, accounts.results, controls.dateRange, groupTypeIndex),
                refresh
            )
        }
    }
    return { accounts, matrix, hogql, source, dateRange: controls.dateRange, interval: controls.interval }
}
