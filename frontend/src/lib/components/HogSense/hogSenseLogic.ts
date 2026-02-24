import { kea, key, path, props, selectors } from 'kea'

import type { hogSenseLogicType } from './hogSenseLogicType'
import type {
    DetectionEntry,
    DetectionResult,
    Finding,
    GroupKnowledgeEntry,
    HogSenseSeverity,
    KnowledgeEntry,
} from './types'

export interface HogSenseLogicProps {
    key: string
    entries: DetectionEntry<any>[]
    knowledge: Record<string, KnowledgeEntry>
    groups?: GroupKnowledgeEntry[]
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

const SEVERITY_RANK: Record<HogSenseSeverity, number> = { info: 0, warning: 1, error: 2 }

function highestSeverity(severities: HogSenseSeverity[]): HogSenseSeverity {
    return severities.reduce((a, b) => (SEVERITY_RANK[b] > SEVERITY_RANK[a] ? b : a))
}

export function resolveFindings(
    results: DetectionResult[],
    knowledge: Record<string, KnowledgeEntry>,
    groups?: GroupKnowledgeEntry[]
): Finding[] {
    const consumed = new Set<string>()
    const findings: Finding[] = []

    if (groups) {
        for (const group of groups) {
            const matched = results.filter((r) => group.ids.includes(r.id))
            if (matched.length === 0) {
                continue
            }
            const labels = matched.map((r) => (r.id in knowledge ? knowledge[r.id].summary : r.id))
            findings.push({
                id: group.id,
                summary: typeof group.summary === 'function' ? group.summary(labels) : group.summary,
                description: typeof group.description === 'function' ? group.description(labels) : group.description,
                severity: highestSeverity(matched.map((r) => r.severity)),
                docs: group.docs,
            })
            for (const r of matched) {
                consumed.add(r.id)
            }
        }
    }

    for (const r of results) {
        if (consumed.has(r.id) || !(r.id in knowledge)) {
            continue
        }
        findings.push({
            ...r,
            summary: knowledge[r.id].summary,
            description: knowledge[r.id].description,
            docs: knowledge[r.id].docs,
        })
    }

    return findings
}

export const hogSenseLogic = kea<hogSenseLogicType>([
    path(['lib', 'components', 'HogSense', 'hogSenseLogic']),
    props({ entityType: undefined, entityId: undefined } as HogSenseLogicProps),
    key((props) => props.key),

    selectors({
        findings: [
            (_, p) => [p.entries, p.knowledge, p.groups, p.context, p.entityType, p.entityId],
            (
                entries: DetectionEntry<any>[],
                knowledge: Record<string, KnowledgeEntry>,
                groups: GroupKnowledgeEntry[] | undefined,
                context: Record<string, any>,
                entityType?: string,
                entityId?: string | number
            ): Finding[] => {
                const results = evaluateDetections(entries, context, { entityType, entityId })
                return resolveFindings(results, knowledge, groups)
            },
        ],
    }),
])
