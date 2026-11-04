import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { retryImport } from 'lib/utils/retryImport'

import { InsightShortId } from '~/types'

import { insightsList } from 'products/product_analytics/frontend/generated/api'

export async function getInsightId(shortId: InsightShortId): Promise<number | undefined> {
    // A static import would put insightLogic and everything it imports on the eager path of every page.
    const { insightLogic } = await retryImport(() => import('scenes/insights/insightLogic'))
    const insightId = insightLogic.findMounted({ dashboardItemId: shortId })?.values?.insight?.id

    return insightId
        ? insightId
        : (await insightsList(String(getCurrentTeamId()), { short_id: shortId })).results[0]?.id
}
