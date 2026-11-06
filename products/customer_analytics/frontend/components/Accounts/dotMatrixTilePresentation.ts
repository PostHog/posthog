import type { ActivityMatrixProps } from '../ProductActivity/activityMatrixTypes'
import type { DotMatrixSourceMapping } from '../ProductActivity/dotMatrixTileConfig'
import { getHogQLActivityMatrix, getHogQLLimitNotice } from '../ProductActivity/hogqlActivityMatrix'
import { EMPTY_ACCOUNT_ACTIVITY_MATRIX, getAccountActivityMatrixProps } from './accountActivityMatrix'
import { getBookActivityMatrixProps } from './bookActivityMatrix'
import type { DotMatrixTileResult } from './dotMatrixTileQuery'

export function getDotMatrixTilePresentation(
    response: DotMatrixTileResult | null,
    selected: string[],
    mapping: DotMatrixSourceMapping,
    weeks: number
): { matrix: ActivityMatrixProps; error: string | null; empty: string; notices: string[] } {
    const fallback = getAccountActivityMatrixProps(EMPTY_ACCOUNT_ACTIVITY_MATRIX, [])
    if (!response) {
        return { matrix: fallback, error: null, empty: '', notices: [] }
    }
    if (response.kind === 'hogql') {
        const mapped = getHogQLActivityMatrix(response.result, mapping)
        return {
            matrix: mapped.props ?? fallback,
            error: mapped.error,
            empty: 'The query returned no rows. Change the query or date range and run it again.',
            notices: [
                ...mapped.notices,
                ...(response.result.hasMore
                    ? ['Showing a limited result. Narrow the date range or query to include all activity.']
                    : [getHogQLLimitNotice(response.result, response.query)].filter(
                          (notice): notice is string => notice !== null
                      )),
            ],
        }
    }
    const reason = response.result.emptyReason
    const messages: Record<string, string> = {
        no_metrics: 'Add a usage metric in project settings to see activity here.',
        no_group_type: 'Choose an account group type in Customer analytics settings to see activity here.',
        no_external_id: "This account isn't linked to any activity yet.",
        empty_book: 'No linked account is available. Check the account link and your access.',
    }
    const matrix =
        response.kind === 'usage_metrics'
            ? getAccountActivityMatrixProps(response.result, selected)
            : getBookActivityMatrixProps(response.result, selected)
    return {
        matrix: reason || !response.result.data.length ? { ...matrix, rows: [], data: [] } : matrix,
        error: null,
        empty: reason ? messages[reason] : `No activity for this account in the last ${weeks} weeks.`,
        notices: response.result.truncated
            ? [
                  response.kind === 'usage_metrics'
                      ? 'Showing the most active people.'
                      : 'Showing a limited result. Narrow the date range or query to include all activity.',
              ]
            : [],
    }
}
