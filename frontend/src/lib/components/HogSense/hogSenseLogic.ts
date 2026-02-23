import { kea, key, path, props, selectors } from 'kea'

import type { hogSenseLogicType } from './hogSenseLogicType'
import type { DetectionEntry, Finding } from './types'

export interface HogSenseLogicProps {
    key: string
    entries: DetectionEntry<any>[]
    context: Record<string, any>
    entityType?: string
    entityId?: string | number
}

export function evaluateDetections<T>(
    entries: DetectionEntry<T>[],
    context: T,
    meta?: { entityType?: string; entityId?: string | number }
): Finding[] {
    return entries
        .filter((entry) => entry.trigger(context))
        .map((entry) => ({
            id: entry.id,
            summary: entry.summary,
            description: entry.description,
            severity: entry.severity,
            docs: entry.docs,
            entityType: meta?.entityType,
            entityId: meta?.entityId,
        }))
}

export const hogSenseLogic = kea<hogSenseLogicType>([
    path(['lib', 'components', 'HogSense', 'hogSenseLogic']),
    props({ entityType: undefined, entityId: undefined } as HogSenseLogicProps),
    key((props) => props.key),

    selectors({
        findings: [
            (_, p) => [p.entries, p.context, p.entityType, p.entityId],
            (
                entries: DetectionEntry<any>[],
                context: Record<string, any>,
                entityType?: string,
                entityId?: string | number
            ): Finding[] => evaluateDetections(entries, context, { entityType, entityId }),
        ],
    }),
])
