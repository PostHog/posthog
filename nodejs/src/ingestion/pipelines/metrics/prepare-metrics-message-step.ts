import { Message } from 'node-rdkafka'

import { QuotaLimiting } from '~/common/services/quota-limiting.service'
import { TeamManager } from '~/common/utils/team-manager'
import { ChunkProcessingStep } from '~/ingestion/framework/builders'
import { isOkResult } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { createDropQuotaLimitedStep } from './drop-quota-limited-step'
import { retryAfterFirstFailure } from './metrics-retry'
import { MetricsUsageAccumulator } from './metrics-usage'
import { createRecordMetricsReceivedStep } from './metrics-usage-steps'
import { MetricsHeaders, createParseMetricsHeadersStep } from './parse-metrics-headers-step'
import { createResolveMetricsTeamStep } from './resolve-metrics-team-step'

const RESOLVE_TEAM_RETRY = { tries: 3, sleepMs: 100, name: 'resolve_metrics_team' }

/** The framework instruments a chunk step once per chunk, and per-message instrumentation costs more than reading the headers. */
export function perMessage<T, U, R extends string = never>(
    step: ProcessingStep<T, U, R>
): ChunkProcessingStep<T, U, R> {
    const chunkStep: ChunkProcessingStep<T, U, R> = (values) => Promise.all(values.map((value) => step(value)))
    Object.defineProperty(chunkStep, 'name', { value: step.name })
    return chunkStep
}

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
