import { Counter } from 'prom-client'

import type { InternalLogs } from './internal-logs'
import type { MutateStage } from './pipeline/log-processing-pipeline'

export const INTERNAL_ATTRIBUTE_PREFIX = 'posthog.internal.'
export const INTERNAL_SOURCE_ATTRIBUTE = `${INTERNAL_ATTRIBUTE_PREFIX}source`

const logsInternalAttributesDroppedCounter = new Counter({
    name: 'logs_ingestion_internal_attributes_dropped_total',
    help: 'posthog.internal.* attribute keys dropped from log records, by reason.',
    labelNames: ['reason'],
})

export function makeInternalAttributesStage(verified: InternalLogs | undefined): MutateStage {
    const allowed = new Set(verified?.attributes.map((suffix) => INTERNAL_ATTRIBUTE_PREFIX + suffix))
    const reason = verified ? 'not_allowed' : 'not_internal'
    return {
        kind: 'mutate',
        name: 'internal_attributes',
        run: (records) => {
            let dropped = 0
            for (const record of records) {
                for (const key of Object.keys(record.attributes ?? {})) {
                    if (key.startsWith(INTERNAL_ATTRIBUTE_PREFIX) && !allowed.has(key)) {
                        delete record.attributes![key]
                        dropped++
                    }
                }
                if (verified) {
                    record.attributes = {
                        ...record.attributes,
                        [INTERNAL_SOURCE_ATTRIBUTE]: JSON.stringify(verified.source),
                    }
                }
            }
            if (dropped > 0) {
                logsInternalAttributesDroppedCounter.inc({ reason }, dropped)
            }
        },
    }
}
