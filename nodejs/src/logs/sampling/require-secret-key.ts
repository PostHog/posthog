import { DependencyUnavailableError } from '~/common/utils/db/error'
import { logger } from '~/common/utils/logger'

import { sentByTeamWithPublicToken } from '../framework/logs-pipeline-context'
import type { LogsIngestionMessage } from '../types'
import type { SamplingRulesCache } from './sampling-rules-cache'

export type RequireSecretKeyDrops = Map<number, { messages: number; records: number; bytes: number; ruleId: string }>

export type RetryOnDependencyUnavailable = <R>(fn: () => Promise<R>) => Promise<R>

async function findRequireSecretKeyRuleId(
    cache: Pick<SamplingRulesCache, 'getCompiledRuleSet'>,
    teamId: number,
    retry: RetryOnDependencyUnavailable
): Promise<string | null> {
    try {
        const ruleSet = await retry(() => cache.getCompiledRuleSet(teamId, 'logs', { throwWhenNeverFetched: true }))
        return ruleSet.requireSecretKeyRuleId
    } catch (error) {
        if (error instanceof DependencyUnavailableError) {
            throw error
        }
        logger.warn('[logs-sampling] require secret key lookup failed, passing the team on', {
            teamId,
            error: String(error),
        })
        return null
    }
}

export async function findRequireSecretKeyDrops<T extends LogsIngestionMessage>(
    messages: T[],
    cache: Pick<SamplingRulesCache, 'getCompiledRuleSet'>,
    rulesEnabledForTeam: (teamId: number) => boolean,
    retry: RetryOnDependencyUnavailable
): Promise<{ dropped: Set<T>; byTeam: RequireSecretKeyDrops }> {
    const candidates = messages.filter(
        (message) => sentByTeamWithPublicToken(message) && rulesEnabledForTeam(message.teamId)
    )
    const teamIds = [...new Set(candidates.map((message) => message.teamId))]
    const ruleIdByTeam = new Map(
        await Promise.all(
            teamIds.map(async (teamId) => [teamId, await findRequireSecretKeyRuleId(cache, teamId, retry)] as const)
        )
    )

    const dropped = new Set<T>()
    const byTeam: RequireSecretKeyDrops = new Map()
    for (const message of candidates) {
        const ruleId = ruleIdByTeam.get(message.teamId)
        if (!ruleId) {
            continue
        }
        dropped.add(message)
        const totals = byTeam.get(message.teamId) ?? { messages: 0, records: 0, bytes: 0, ruleId }
        totals.messages++
        totals.records += message.recordCount
        totals.bytes += message.bytesUncompressedRecords
        byTeam.set(message.teamId, totals)
    }
    return { dropped, byTeam }
}
