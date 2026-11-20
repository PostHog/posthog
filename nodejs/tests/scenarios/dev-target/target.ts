import { randomUUID } from 'crypto'

import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import { DEV_CAPS } from '../cards/target'
import type { Environment } from '../environment/environment'
import type { Wiring } from '../environment/topology'
import { Emit, captureWebhook } from '../generator/traffic'
import type { RunTarget } from '../runner/runner'
import type { DevConfig } from './config'
import { WorkflowRuns, checkOffersToken, exitActionOf, receiptTruth, unfinishedOf, workflowRuns } from './reads'

const METRICS_EVERY_MS = 10_000
const SDK_INFO = 'posthog-scenario-runner/1'

type CaptureResults = { results?: Record<string, { result: string; details?: string }> }

export const captureEmit = (config: DevConfig, runId: string, budget: number): Emit => {
    let offered = 0
    return async (unit, event, properties) => {
        offered += 1
        if (offered > budget) {
            throw new Error(`the run spent its budget of ${budget} dev units before ${unit.unitId}`)
        }
        const uuid = randomUUID()
        const now = new Date().toISOString()
        try {
            const response = await internalFetch(`${config.host}/i/v1/analytics/events`, {
                method: 'POST',
                headers: {
                    authorization: `Bearer ${config.offers.token}`,
                    'content-type': 'application/json',
                    'user-agent': SDK_INFO,
                    'posthog-sdk-info': SDK_INFO,
                    'posthog-attempt': '1',
                    'posthog-request-id': randomUUID(),
                    'posthog-request-timestamp': now,
                },
                body: JSON.stringify({
                    created_at: now,
                    batch: [
                        {
                            event,
                            uuid,
                            distinct_id: unit.unitId,
                            timestamp: now,
                            properties: { ...properties, run_id: runId },
                        },
                    ],
                }),
            })
            const text = await response.text()
            const answer = response.status === 200 ? (parseJSON(text) as CaptureResults).results?.[uuid] : undefined
            if (answer?.result === 'ok' || answer?.result === 'warning') {
                return { accepted: true }
            }
            const outcome = answer ? [answer.result, answer.details].filter(Boolean).join(' ') : text.slice(0, 200)
            return { accepted: false, status: response.status, outcome }
        } catch (error) {
            return { accepted: false, transportError: String(error) }
        }
    }
}

const monthStart = (): string => {
    const now = new Date()
    return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1)).toISOString()
}

const hourStart = (): string => {
    const now = new Date()
    now.setUTCMinutes(0, 0, 0)
    return now.toISOString()
}

const minus = (runs: WorkflowRuns, base: WorkflowRuns): WorkflowRuns => ({
    triggered: runs.triggered - base.triggered,
    exited: runs.exited - base.exited,
    quota_limited: runs.quota_limited - base.quota_limited,
})

export function devTarget(config: DevConfig): RunTarget {
    return {
        name: 'dev',
        open(loaded, runId) {
            // The metrics table merges an hour's rows under one of their timestamps, so a window must start on the hour.
            const since = hourStart()
            const { ratePerSecond } = captureWebhook.profile.parse(loaded.profile.traffic[captureWebhook.name])
            let before: Promise<{ exitId: string; base: WorkflowRuns }> | undefined
            const baseline = (): Promise<{ exitId: string; base: WorkflowRuns }> =>
                (before ??= exitActionOf(config).then(async (exitId) => ({
                    exitId,
                    base: await workflowRuns(config, since, 'hour', exitId),
                })))
            let read: { at: number; runs: Promise<WorkflowRuns> } | undefined
            const runsSince = (): Promise<WorkflowRuns> => {
                if (read === undefined || Date.now() - read.at >= METRICS_EVERY_MS) {
                    const runs = baseline().then(async ({ exitId, base }) =>
                        minus(await workflowRuns(config, since, 'hour', exitId), base)
                    )
                    read = { at: Date.now(), runs }
                }
                return read.runs
            }
            const unfinishedJobs = (): Promise<number> => runsSince().then(unfinishedOf)
            const { teamId, workflowId } = config.offers
            return {
                truth: receiptTruth(config, runId),
                probe: { unfinishedJobs, runningJobs: unfinishedJobs },
                fetchRetries: 0,
                groups: [],
                connect: () => Promise.resolve(),
                seed: async () => {
                    const month = await workflowRuns(config, monthStart(), 'day')
                    if (month.quota_limited > 0) {
                        throw new Error(`dev quota limited ${month.quota_limited} runs of the workflow this month`)
                    }
                    if (month.triggered + DEV_CAPS.units > config.monthlyRuns) {
                        throw new Error(
                            `the workflow ran ${month.triggered} times this month, so a run of up to ${DEV_CAPS.units} units could pass DEV_TARGET_MONTHLY_RUNS`
                        )
                    }
                    const { base } = await baseline()
                    if (unfinishedOf(base) > 0) {
                        throw new Error(
                            `the workflow has ${unfinishedOf(base)} runs unfinished from before this run, which would blur its count`
                        )
                    }
                    await checkOffersToken(config)
                    return { teamIds: [teamId], flowIds: { [captureWebhook.name]: { [teamId]: workflowId } } }
                },
                // Halts a ramp before dev's quota or a backlog the workflow cannot drain turns into a dev incident.
                limit: async ({ scale }) => {
                    const runs = await runsSince()
                    const minute = ratePerSecond * scale * 60
                    return runs.quota_limited > 0
                        ? `dev quota limited ${runs.quota_limited} runs of the workflow at the ${scale}x step`
                        : unfinishedOf(runs) > minute
                          ? `the workflow had ${unfinishedOf(runs)} runs unfinished at the ${scale}x step, more than a minute of offers`
                          : undefined
                },
                probes: () =>
                    Promise.resolve({
                        commits: () => [],
                        queue: () => [],
                        stop: () => Promise.resolve({ writer: [], queue: [] }),
                    }),
                offers: () => Promise.resolve({ emit: captureEmit(config, runId, DEV_CAPS.units) }),
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
