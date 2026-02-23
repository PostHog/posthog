import { kea, key, path, props, selectors } from 'kea'

import type { hogSenseLogicType } from './hogSenseLogicType'
import type { DetectionEntry, DetectionResult, Finding, KnowledgeEntry } from './types'

export interface HogSenseLogicProps {
    key: string
    entries: DetectionEntry<any>[]
    knowledge: Record<string, KnowledgeEntry>
    context: Record<string, any>
    entityType?: string
    entityId?: string | number
}

export function evaluateDetections<T>(
    entries: DetectionEntry<T>[],
    context: T,
    meta?: { entityType?: string; entityId?: string | number }
): DetectionResult[] {
    return entries
        .filter((entry) => entry.trigger(context))
        .map((entry) => ({
            id: entry.id,
            severity: entry.severity,
            entityType: meta?.entityType,
            entityId: meta?.entityId,
        }))
}

export function resolveFindings(results: DetectionResult[], knowledge: Record<string, KnowledgeEntry>): Finding[] {
    return results
        .filter((r) => r.id in knowledge)
        .map((r) => ({
            ...r,
            summary: knowledge[r.id].summary,
            description: knowledge[r.id].description,
            docs: knowledge[r.id].docs,
        }))
}

export const hogSenseLogic = kea<hogSenseLogicType>([
    path(['lib', 'components', 'HogSense', 'hogSenseLogic']),
    props({ entityType: undefined, entityId: undefined } as HogSenseLogicProps),
    key((props) => props.key),

    selectors({
        findings: [
            (_, p) => [p.entries, p.knowledge, p.context, p.entityType, p.entityId],
            (
                entries: DetectionEntry<any>[],
                knowledge: Record<string, KnowledgeEntry>,
                context: Record<string, any>,
                entityType?: string,
                entityId?: string | number
            ): Finding[] => {
                const results = evaluateDetections(entries, context, { entityType, entityId })
                return resolveFindings(results, knowledge)
            },
        ],
    }),
])
