import { internalFetch } from '~/common/utils/request'

import type { Environment } from '../environment/environment'
import type { Wiring } from '../environment/topology'
import { Emit, captureWebhook } from '../generator/traffic'
import type { RunTarget } from '../runner/runner'
import type { DevConfig } from './config'
import { checkOffersToken, receiptTruth, unfinishedRuns } from './reads'

const METRICS_EVERY_MS = 10_000

export const captureEmit =
    (config: DevConfig, runId: string): Emit =>
    async (unit, event, properties) => {
        const response = await internalFetch(`${config.host}/i/v0/e/`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({
                api_key: config.offers.token,
                event,
                distinct_id: unit.unitId,
                properties: { ...properties, run_id: runId },
            }),
        })
        // The journal keeps a refused event offer out of every invariant, so the run fails instead of passing short.
        if (response.status !== 200) {
            throw new Error(`capture refused ${unit.unitId} with ${response.status}`)
        }
        return { accepted: true }
    }

export function devTarget(config: DevConfig): RunTarget {
    return {
        name: 'dev',
        open(_loaded, runId) {
            const since = new Date().toISOString()
            let read: { at: number; runs: Promise<number> } | undefined
            const unfinishedJobs = (): Promise<number> => {
                if (read === undefined || Date.now() - read.at >= METRICS_EVERY_MS) {
                    read = { at: Date.now(), runs: unfinishedRuns(config, since) }
                }
                return read.runs
            }
            const { teamId, workflowId } = config.offers
            return {
                truth: receiptTruth(config, runId),
                probe: { unfinishedJobs, runningJobs: unfinishedJobs },
                fetchRetries: 0,
                groups: [],
                connect: () => Promise.resolve(),
                seed: async () => {
                    await unfinishedJobs()
                    await checkOffersToken(config)
                    return { teamIds: [teamId], flowIds: { [captureWebhook.name]: { [teamId]: workflowId } } }
                },
                probes: () =>
                    Promise.resolve({
                        commits: () => [],
                        queue: () => [],
                        stop: () => Promise.resolve({ writer: [], queue: [] }),
                    }),
                offers: () => Promise.resolve({ emit: captureEmit(config, runId) }),
                writeLogTails: () => Promise.resolve(),
                close: () => Promise.resolve(),
            }
        },
    }
}

const WIRING: Wiring = {
    recordedAt: new Date(0).toISOString(),
    hash: 'dev',
    processes: [],
    consumers: [],
    databases: [],
}

export function devEnvironment(): Environment {
    const none = (what: string) => (): never => {
        throw new Error(`the dev target has no ${what}`)
    }
    return {
        up: () => Promise.resolve(),
        down: () => Promise.resolve(),
        reset: (settings, replicas) =>
            Object.keys(settings).length + Object.keys(replicas ?? {}).length === 0
                ? Promise.resolve()
                : Promise.reject(new Error('the dev target runs with the settings and replicas it has')),
        edgeUrl: none('provider edge'),
        role: none('roles to address'),
        roles: () => [],
        actuate: () => Promise.reject(new Error('the dev target takes no valves')),
        dependencyHealth: () => Promise.resolve({ healthy: true, down: [] }),
        exits: () => [],
        groupLag: () => Promise.reject(new Error('the dev target has no consumer groups to read')),
        wiring: () => Promise.resolve(WIRING),
        writerCpu: () => Promise.reject(new Error('the dev target has no Aurora writer to read')),
    }
}
