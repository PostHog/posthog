import { InsightDataThatVariesWithContext, InsightModel } from '~/types'

/**
 * When changing an InsightModel there is some data that applied no matter where the insight is displayed or changed
 * And other data that varies depending on whether the insight is on a dashboard and which dashboard it is on
 * This is a convenience method to ensure that when receiving changes to an insight
 * the correct dashboard specific data is kept
 *
 * returns an updated copy of the target
 *
 * @param target the InsightModel to update
 * @param source the Insight data that is within a particular dashboard context
 */
export function mergeWithDashboardTile<T extends InsightModel | Partial<InsightModel>>(
    target: T,
    source: InsightDataThatVariesWithContext
): T {
    const updatedTarget = { ...target }

    updatedTarget.result = source.result || []
    updatedTarget.layouts = source.layouts || {}
    updatedTarget.color = source.color || null
    updatedTarget.last_refresh = source.last_refresh || null
    updatedTarget.filters = source.filters
    updatedTarget.filters_hash = source.filters_hash || ''

    return updatedTarget
}
