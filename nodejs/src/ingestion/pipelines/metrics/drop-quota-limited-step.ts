import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { metricMessageDroppedCounter } from './metrics'
import { MetricsUsageAccumulator } from './metrics-usage'

export interface DropQuotaLimitedInput {
    token: string
    teamId: number
    bytesUncompressed: number
    recordCount: number
    usage: MetricsUsageAccumulator
}

export function createDropQuotaLimitedStep<T extends DropQuotaLimitedInput>(
    quotaLimiting: Pick<QuotaLimiting, 'isTeamTokenQuotaLimited'>
): ProcessingStep<T, T> {
    return async function dropQuotaLimitedStep(input) {
        if (await quotaLimiting.isTeamTokenQuotaLimited(input.token, 'metrics_mb_ingested')) {
            input.usage.recordDropped(input.teamId, input.bytesUncompressed, input.recordCount)
            metricMessageDroppedCounter.inc({ reason: 'quota_limited', team_id: input.teamId.toString() })
            return drop('quota_limited')
        }
        return ok(input)
    }
}
