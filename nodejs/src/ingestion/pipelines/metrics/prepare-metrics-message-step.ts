import { Message } from 'node-rdkafka'

import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { TeamManager } from '~/common/utils/team-manager'
import { isOkResult } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { createDropQuotaLimitedStep } from './drop-quota-limited-step'
import { retryAfterFirstFailure } from './metrics-retry'
import { MetricsUsageAccumulator } from './metrics-usage'
import { createRecordMetricsReceivedStep } from './metrics-usage-steps'
import { MetricsHeaders, createParseMetricsHeadersStep } from './parse-metrics-headers-step'
import { createResolveMetricsTeamStep } from './resolve-metrics-team-step'

const RESOLVE_TEAM_RETRY = { tries: 3, sleepMs: 100, name: 'resolve_metrics_team' }

export function createPrepareMetricsMessageStep<T extends { message: Message; usage: MetricsUsageAccumulator }>(
    teamManager: Pick<TeamManager, 'getTeam' | 'getTeamByToken'>,
    quotaLimiting: Pick<QuotaLimiting, 'isTeamTokenQuotaLimited'>
): ProcessingStep<T, T & MetricsHeaders & { teamId: number }> {
    const parseHeaders = createParseMetricsHeadersStep<T>()
    const resolveTeam = createResolveMetricsTeamStep<T & MetricsHeaders>(teamManager)
    const recordReceived = createRecordMetricsReceivedStep<T & MetricsHeaders & { teamId: number }>()
    const dropQuotaLimited = createDropQuotaLimitedStep<T & MetricsHeaders & { teamId: number }>(quotaLimiting)

    return async function prepareMetricsMessageStep(input) {
        const parsed = await parseHeaders(input)
        if (!isOkResult(parsed)) {
            return parsed
        }
        const resolved = await retryAfterFirstFailure(() => resolveTeam(parsed.value), RESOLVE_TEAM_RETRY)
        if (!isOkResult(resolved)) {
            return resolved
        }
        const received = await recordReceived(resolved.value)
        if (!isOkResult(received)) {
            return received
        }
        return await dropQuotaLimited(received.value)
    }
}
