import api from 'lib/api'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { retryImport } from 'lib/utils/retryImport'

import { InsightShortId } from '~/types'

export async function getInsightId(shortId: InsightShortId): Promise<number | undefined> {
    // A static import would put insightLogic and everything it imports on the eager path of every page.
    const { insightLogic } = await retryImport(() => import('scenes/insights/insightLogic'))
    const insightId = insightLogic.findMounted({ dashboardItemId: shortId })?.values?.insight?.id

    return insightId
        ? insightId
        : // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. Use insightsList() from 'products/product_analytics/frontend/generated/api' instead.
          (await api.get(`api/projects/${getCurrentTeamId()}/insights/?short_id=${encodeURIComponent(shortId)}`))
              .results[0]?.id
}
