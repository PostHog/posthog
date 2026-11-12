import { Gauge } from 'prom-client'

import { RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

import type { CdpConfig } from '../../config'
import { CyclotronJobInvocation } from '../../types'
import { positiveInteger } from './crash-guard'

const trackers = new Set<QuarantineTracker>()

// The CdpHogdlqFunctionRepeatedlyQuarantined alert in charts reads this name and its labels, so a rename
// silences it. A counter would not do: the dead letter worker crashes on the invocations it quarantines, and a
// crash loses the increments since the last scrape.
new Gauge({
    name: 'cdp_quarantined_functions',
    help: 'Distinct invocations quarantined within CDP_QUARANTINE_ESCALATION_WINDOW_SECONDS, for each function at or above CDP_QUARANTINE_ESCALATION_THRESHOLD. Read from Valkey at scrape time, and empty when Valkey does not answer in time.',
    labelNames: ['function_id', 'team_id'],
    async collect() {
        const found = await Promise.all([...trackers].map((tracker) => tracker.functionsAtThreshold()))
        this.reset()
        for (const { functionId, teamId, quarantined } of found.flat()) {
            this.labels({ function_id: functionId, team_id: teamId }).set(quarantined)
        }
    },
})

// Holds each function with a quarantine in the window, so a scrape reads only those functions.
const QUARANTINED_FUNCTIONS_KEY = 'cdp:quarantined-functions'

const quarantinedInvocationsKey = (functionId: string): string => `cdp:quarantined-invocations:${functionId}`

const quarantinedFunctionTeamKey = (functionId: string): string => `cdp:quarantined-function-team:${functionId}`

// Prometheus gives up on a scrape after its own timeout, and an empty gauge beats a failed scrape.
const SCRAPE_TIMEOUT_MS = 2_000

export type QuarantineTrackerConfig = {
    threshold: number
    windowSeconds: number
}

type QuarantinedFunction = { functionId: string; teamId: string; quarantined: number }

/**
 * Counts the distinct quarantined invocations of each hog function in Valkey. The count is by function id
 * alone, so an invocation whose payload lost its team still counts. A person decides what happens to the
 * function, so this only reports it through cdp_quarantined_functions.
 */
export class QuarantineTracker {
    constructor(
        private valkey: RedisV2,
        private config: QuarantineTrackerConfig
    ) {
        trackers.add(this)
    }

    public stop(): void {
        trackers.delete(this)
    }

    /** Never throws, because the quarantine must commit whether or not its function could be counted. */
    public async observe(invocations: CyclotronJobInvocation[]): Promise<void> {
        const byFunction = new Map<string, { ids: Set<string>; teamId?: number }>()
        for (const { functionId, id, teamId } of invocations) {
            if (functionId && id) {
                const fn = byFunction.get(functionId) ?? { ids: new Set<string>() }
                fn.ids.add(id)
                if (Number.isInteger(teamId) && teamId > 0) {
                    fn.teamId = teamId
                }
                byFunction.set(functionId, fn)
            }
        }
        if (byFunction.size === 0) {
            return
        }

        try {
            const { windowSeconds } = this.config
            const now = Date.now()
            const results = await this.valkey.usePipeline({ name: 'cdp-quarantined-invocations' }, (pipeline) => {
                for (const [functionId, { ids, teamId }] of byFunction) {
                    const key = quarantinedInvocationsKey(functionId)
                    pipeline.zremrangebyscore(key, '-inf', now - windowSeconds * 1000)
                    // NX keeps the time of the first quarantine, so a duplicate on the topic neither counts again
                    // nor stretches the window.
                    pipeline.zadd(key, 'NX', ...[...ids].flatMap((id) => [now, id]))
                    pipeline.expire(key, windowSeconds)
                    if (teamId !== undefined) {
                        pipeline.set(quarantinedFunctionTeamKey(functionId), teamId, 'EX', windowSeconds)
                    }
                    pipeline.zadd(QUARANTINED_FUNCTIONS_KEY, now, functionId)
                }
                pipeline.zremrangebyscore(QUARANTINED_FUNCTIONS_KEY, '-inf', now - windowSeconds * 1000)
                pipeline.expire(QUARANTINED_FUNCTIONS_KEY, windowSeconds)
            })
            const failed = results?.find(([error]) => error)
            if (failed) {
                throw failed[0]
            }
        } catch (error) {
            logger.warn('☠️', 'could not count quarantined invocations', {
                functionIds: [...byFunction.keys()],
                error: String(error),
            })
        }
    }

    /** Reads the functions at or above the threshold. Returns none when Valkey fails or is slow. */
    public async functionsAtThreshold(): Promise<QuarantinedFunction[]> {
        let timer: NodeJS.Timeout | undefined
        const timeout = new Promise<never>((_, reject) => {
            timer = setTimeout(() => reject(new Error(`timed out after ${SCRAPE_TIMEOUT_MS}ms`)), SCRAPE_TIMEOUT_MS)
        })
        try {
            return await Promise.race([this.readFunctionsAtThreshold(), timeout])
        } catch (error) {
            logger.warn('☠️', 'could not read the quarantined functions for the gauge', { error: String(error) })
            return []
        } finally {
            clearTimeout(timer)
        }
    }

    private async readFunctionsAtThreshold(): Promise<QuarantinedFunction[]> {
        const { threshold, windowSeconds } = this.config
        const since = Date.now() - windowSeconds * 1000
        const found = await this.valkey.useClient({ name: 'cdp-quarantined-functions' }, async (client) => {
            const functionIds = await client.zrangebyscore(QUARANTINED_FUNCTIONS_KEY, since, '+inf')
            if (functionIds.length === 0) {
                return []
            }
            const pipeline = client.pipeline()
            for (const functionId of functionIds) {
                pipeline.zcount(quarantinedInvocationsKey(functionId), since, '+inf')
                pipeline.get(quarantinedFunctionTeamKey(functionId))
            }
            const results = await pipeline.exec()
            if (!results) {
                throw new Error('Valkey returned no pipeline results')
            }
            return functionIds.flatMap((functionId, i) => {
                const [[countError, quarantined], [teamError, teamId]] = getRedisPipelineResults(results, i, 2)
                if (countError || teamError) {
                    throw countError ?? teamError
                }
                return Number(quarantined) >= threshold
                    ? [{ functionId, teamId: String(teamId ?? ''), quarantined: Number(quarantined) }]
                    : []
            })
        })
        return found ?? []
    }
}

type QuarantineTrackerServiceConfig = Pick<
    CdpConfig,
    'CDP_QUARANTINE_ESCALATION_THRESHOLD' | 'CDP_QUARANTINE_ESCALATION_WINDOW_SECONDS'
>

export function createQuarantineTracker(config: QuarantineTrackerServiceConfig, valkey: RedisV2): QuarantineTracker {
    return new QuarantineTracker(valkey, {
        threshold: positiveInteger(config, 'CDP_QUARANTINE_ESCALATION_THRESHOLD'),
        windowSeconds: positiveInteger(config, 'CDP_QUARANTINE_ESCALATION_WINDOW_SECONDS'),
    })
}
