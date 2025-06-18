import { urls } from 'scenes/urls'

import { nodeKindToInsightType } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import type { Node } from '~/queries/schema/schema-general'
import { NodeKind } from '~/queries/schema/schema-general'
import type { QueryBasedInsightModel } from '~/types'
import { InsightType } from '~/types'

const APP_ORIGIN = 'https://app.posthog.com'

/**
 * Build a canonical definition-based insight link ("template link").
 * The link always points to `/insights/new` on app.posthog.com and includes:
 *   #insight=<InsightType>&q=<URL-encoded JSON definition>
 *
 * It works for both saved insights (where `query` is persisted on the model)
 * and unsaved/draft insights (pass the raw query object).
 */
export function getInsightDefinitionUrl(
    insight: Pick<QueryBasedInsightModel, 'query'> | { query: Node<Record<string, any>> }
): string {
    if (!insight?.query) {
        throw new Error('getInsightDefinitionUrl: insight.query is required')
    }

    // Derive InsightType from the query where possible so the #insight=<TYPE> hash param is present
    let insightType: InsightType | undefined
    type InsightVizNode = { kind: NodeKind.InsightVizNode; source?: { kind?: string } }
    const kind = (
        insight.query.kind === NodeKind.InsightVizNode
            ? (insight.query as InsightVizNode).source?.kind
            : insight.query.kind
    ) as keyof typeof nodeKindToInsightType | undefined

    if (kind && kind in nodeKindToInsightType) {
        insightType = nodeKindToInsightType[kind as keyof typeof nodeKindToInsightType]
    }

    const relativeUrl = urls.insightNew({ query: insight.query, type: insightType })

    // Ensure the link is project-agnostic (`/project/<id>` may get injected elsewhere)
    const cleanedPath = relativeUrl.replace(/^\/project\/[^/]+/, '')

    return `${APP_ORIGIN}${cleanedPath}`
}
