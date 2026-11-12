import { Counter } from 'prom-client'

import { RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'

import type { CdpConfig } from '../../config'
import { CyclotronJobInvocation, HogFunctionType } from '../../types'
import { dualRead, dualWrite } from '../../utils/dual-store'
import { HogWatcherService, HogWatcherState, sameWatcherState } from '../monitoring/hog-watcher.service'
import { positiveInteger } from './crash-guard'

// On-call alerts read these two names, so a rename silences them.
const quarantinedFunctionsNew = new Counter({
    name: 'cdp_quarantined_functions_new_total',
    help: 'Functions that got a quarantined invocation. A function counts at most once per 10 minutes.',
})

const functionsAutoDisabled = new Counter({
    name: 'cdp_functions_auto_disabled_total',
    help: 'Functions disabled because too many of their invocations were quarantined within the window.',
})

const quarantineDisableChecks = new Counter({
    name: 'cdp_quarantine_disable_checks_total',
    help: 'Functions checked for a disable after a quarantine, by outcome. unavailable means Valkey, the watcher or the function could not be read, so the function was not disabled.',
    labelNames: ['outcome'],
})

type CheckOutcome =
    | 'below_threshold'
    | 'disabled'
    | 'automatic_disable_off'
    | 'already_disabled'
    | 'forcefully_set'
    | 'function_not_found'
    | 'unavailable'

const NEW_QUARANTINE_WINDOW_SECONDS = 10 * 60

const quarantinedInvocationsKey = (functionId: string): string => `cdp:quarantined-invocations:${functionId}`

export const recentlyQuarantinedKey = (functionId: string): string => `cdp:recently-quarantined:${functionId}`

export type QuarantineAutoDisableConfig = {
    threshold: number
    windowSeconds: number
    autoDisable: boolean
}

export type QuarantineAutoDisableDeps = {
    valkey: RedisV2
    getHogFunction: (id: string) => Promise<HogFunctionType | null>
    hogWatcher: HogWatcherService
    hogWatcherMirror: HogWatcherService
}

type CountedFunction = { functionId: string; quarantined: number }

/**
 * Disables a hog function whose invocations keep crashing the dead letter worker. The count is by function id
 * alone, so an invocation whose payload lost its team still counts, and the team comes from the function row.
 */
export class QuarantineAutoDisableService {
    constructor(
        private deps: QuarantineAutoDisableDeps,
        private config: QuarantineAutoDisableConfig
    ) {}

    /** Never throws, because the quarantine must commit whether or not its function could be counted. */
    public async observe(invocations: CyclotronJobInvocation[]): Promise<void> {
        const byFunction = new Map<string, Set<string>>()
        for (const { functionId, id } of invocations) {
            if (functionId && id) {
                byFunction.set(functionId, (byFunction.get(functionId) ?? new Set()).add(id))
            }
        }
        if (byFunction.size === 0) {
            return
        }

        let counted: CountedFunction[]
        try {
            counted = await this.count(byFunction)
        } catch (error) {
            quarantineDisableChecks.labels('unavailable').inc(byFunction.size)
            logger.warn('☠️', 'could not count quarantined invocations, so no function was checked for a disable', {
                functionIds: [...byFunction.keys()],
                error: String(error),
            })
            return
        }

        await Promise.all(
            counted.map(async (fn) => {
                const outcome = await this.disableIfOverThreshold(fn).catch((error): CheckOutcome => {
                    logger.warn('☠️', 'could not check a quarantined function for a disable', {
                        functionId: fn.functionId,
                        error: String(error),
                    })
                    return 'unavailable'
                })
                quarantineDisableChecks.labels(outcome).inc()
            })
        )
    }

    private async count(byFunction: Map<string, Set<string>>): Promise<CountedFunction[]> {
        const { windowSeconds } = this.config
        const now = Date.now()
        const functionIds = [...byFunction.keys()]
        const results = await this.deps.valkey.usePipeline({ name: 'cdp-quarantined-invocations' }, (pipeline) => {
            for (const functionId of functionIds) {
                const key = quarantinedInvocationsKey(functionId)
                pipeline.zremrangebyscore(key, '-inf', now - windowSeconds * 1000)
                // NX keeps the time of the first quarantine, so a duplicate on the topic neither counts again
                // nor stretches the window.
                pipeline.zadd(key, 'NX', ...[...byFunction.get(functionId)!].flatMap((id) => [now, id]))
                pipeline.zcard(key)
                pipeline.expire(key, windowSeconds)
                pipeline.set(recentlyQuarantinedKey(functionId), '1', 'EX', NEW_QUARANTINE_WINDOW_SECONDS, 'NX')
            }
        })
        if (!results) {
            throw new Error('Valkey returned no pipeline results')
        }

        return functionIds.map((functionId, i) => {
            const ops = getRedisPipelineResults(results, i, 5)
            const failed = ops.find(([error]) => error)
            if (failed) {
                throw failed[0]
            }
            if (ops[4][1] === 'OK') {
                quarantinedFunctionsNew.inc()
            }
            return { functionId, quarantined: ops[2][1] as number }
        })
    }

    private async disableIfOverThreshold({ functionId, quarantined }: CountedFunction): Promise<CheckOutcome> {
        const { threshold, windowSeconds, autoDisable } = this.config
        if (quarantined < threshold) {
            return 'below_threshold'
        }
        const context = { functionId, quarantined, threshold, windowSeconds }
        if (!autoDisable) {
            logger.warn('☠️', 'would disable a function whose invocations keep getting quarantined', context)
            return 'automatic_disable_off'
        }

        const hogFunction = await this.deps.getHogFunction(functionId)
        if (!hogFunction) {
            return 'function_not_found'
        }

        const { hogWatcher, hogWatcherMirror } = this.deps
        const { state } = await dualRead(
            'hog-watcher.getPersistedState',
            () => hogWatcher.getPersistedState(functionId),
            () => hogWatcherMirror.getPersistedState(functionId),
            sameWatcherState
        )
        // The rating path leaves these states alone too: a disabled function stays disabled until a person
        // re-enables it, and a forced state belongs to whoever set it.
        if (state === HogWatcherState.disabled) {
            return 'already_disabled'
        }
        if (state >= HogWatcherState.forcefully_degraded) {
            return 'forcefully_set'
        }

        await dualWrite(
            'hog-watcher.forceStateChange',
            () => hogWatcher.forceStateChange(hogFunction, HogWatcherState.disabled),
            () => hogWatcherMirror.forceStateChange(hogFunction, HogWatcherState.disabled)
        )
        functionsAutoDisabled.inc()
        logger.error('☠️', 'disabled a function whose invocations keep getting quarantined', {
            ...context,
            teamId: hogFunction.team_id,
            previousState: HogWatcherState[state],
        })
        return 'disabled'
    }
}

type QuarantineAutoDisableServiceConfig = Pick<
    CdpConfig,
    'CDP_QUARANTINE_DISABLE_THRESHOLD' | 'CDP_QUARANTINE_DISABLE_WINDOW_SECONDS' | 'CDP_QUARANTINE_AUTO_DISABLE'
>

export function createQuarantineAutoDisable(
    config: QuarantineAutoDisableServiceConfig,
    deps: QuarantineAutoDisableDeps
): QuarantineAutoDisableService {
    return new QuarantineAutoDisableService(deps, {
        threshold: positiveInteger(config, 'CDP_QUARANTINE_DISABLE_THRESHOLD'),
        windowSeconds: positiveInteger(config, 'CDP_QUARANTINE_DISABLE_WINDOW_SECONDS'),
        autoDisable: config.CDP_QUARANTINE_AUTO_DISABLE,
    })
}
