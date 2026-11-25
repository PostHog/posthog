import { once } from 'events'
import { existsSync, mkdirSync, realpathSync } from 'fs'
import os from 'os'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'

import { waitForExpect } from '~/tests/helpers/expectations'
import { isPortFree } from '~/tests/helpers/service-process'

import { Profile, ROLE_RESTART_BACKOFF_MS } from '../cards'
import { Aws, awsCli } from '../cloud/aws'
import type { RunManifest } from '../cloud/lease'
import type { CpuPoint } from '../judge/bars'
import type { DriveWindow } from '../judge/measurements'
import type { WriterSample } from '../probe/writer-probe'
import { FaultHold, FaultRule, ProviderEdge, startProviderEdge } from '../provider-edge'
import { FailoverJournal, FailoverOptions, failOver, sqlIdentityOf } from './failover'
import { nameOf } from './identity'
import { ProbeProcess, startProbeProcess } from './probe-process'
import { StackConflictError, holdRunLock, planCleanup, readProcs, strangerConflict, terminate } from './processes'
import {
    ConsumerGroup,
    Replicas,
    Role,
    RoleId,
    RoleSpec,
    consumerGroupsOf,
    intakeTopicsOf,
    portOf,
    roleIdsOf,
    roleSpecs,
    secretsOf,
} from './roles'
import {
    Hogli,
    ProbeFailure,
    STACK,
    createTopics,
    cyclotronUrlOf,
    deleteUnfinishedJobs,
    forgetSesBucket,
    groupLag,
    groupMembers,
    missingTemplates,
    postgresServersOf,
    rolesNotReady,
    seekToEnd,
    startStack,
    syncTemplates,
    terminateRoleConnections,
} from './stack'
import { RoleExit, createSupervisor } from './supervisor'
import {
    WORKFLOWS_ADAPTER,
    Wiring,
    kafkaGroups,
    postgresClients,
    scenarioGroupsOf,
    unionOf,
    wiringOf,
} from './topology'
import { writerCpuOf } from './writer-cpu'

export type { RoleExit } from './supervisor'

export interface Environment {
    up(signal: AbortSignal): Promise<void>
    reset(settings: Profile['settings'], replicas?: Replicas): Promise<void>
    edgeUrl(): string
    role(name: Role): RoleHandle
    roles(): RoleHandle[]
    actuate(action: Action): Promise<Actuation>
    dependencyHealth(): Promise<{ healthy: boolean; down: ProbeFailure[] }>
    exits(): RoleExit[]
    groupLag(group: string): Promise<number>
    wiring(signal: AbortSignal): Promise<Wiring>
    writerCpu(manifest: RunManifest, window: DriveWindow, signal: AbortSignal): Promise<CpuPoint[]>
    down(): Promise<void>
}

export type RoleHandle = { name: Role; replica: number; url: string; metricsUrl: string }

export type Action =
    | { kind: 'kill'; role: Role }
    | { kind: 'freeze'; role: Role }
    | { kind: 'pg.terminate'; share: number }
    | { kind: 'edge.fault'; rule: FaultRule }
    | {
          kind: 'rds.failover'
          manifest: RunManifest
          holdMs: number
          commits: () => readonly WriterSample[]
          signal: AbortSignal
      }

export type Actuation = FaultHold & { journal?(): FailoverJournal; refused?(): boolean }

const NODEJS_DIR = realpathSync(path.resolve(__dirname, '..', '..', '..'))
const REPO_ROOT = path.dirname(NODEJS_DIR)
const TSX = path.join(NODEJS_DIR, 'node_modules', '.bin', 'tsx')
const EDGE_PORT = 4566
const EDGE = { port: EDGE_PORT, owner: 'provider edge' }
const TEMPLATES_WITHIN_MS = 120_000
const ROLE_HEALTHY_WITHIN_MS = 120_000
const GROUP_DRAINS_WITHIN_MS = 60_000
const GROUPS_EMPTY_WITHIN_MS = 45_000
const STOP_GRACE_MS = 10_000
const PROBE_INTERVAL_MS = 1000
const KILL_OBSERVED_WITHIN_MS = 10_000
const FREEZE_OBSERVED_WITHIN_MS = 10_000
const DROP_SWEEP_EVERY_MS = 100

const portsOf = (specs: RoleSpec[]): { port: number; owner: string }[] =>
    specs.map((spec) => ({ port: spec.port, owner: nameOf(spec) }))

const handleOf = (id: RoleId): RoleHandle => ({
    name: id.role,
    replica: id.replica,
    url: `http://127.0.0.1:${portOf(id)}`,
    metricsUrl: `http://127.0.0.1:${portOf(id)}/_metrics`,
})

export function defaultStateDir(env: NodeJS.ProcessEnv): string {
    return path.join(env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache'), 'posthog-scenarios')
}

async function groupsWithMembers(groups: ConsumerGroup[], docker: string): Promise<string[]> {
    const members = await Promise.all(groups.map(({ group }) => groupMembers(group, docker)))
    return groups.filter((_, i) => members[i] > 0).map(({ group }) => group)
}

export type EnvironmentOptions = {
    hogli: Hogli
    docker: string
    postgresUrl: string
    sesRateLimiterValkey: { host: string; port: number }
    roleHealthyWithinMs: number
    aws: Aws
    failover: Partial<Pick<FailoverOptions, 'identity' | 'pollMs' | 'observeWithinMs'>>
}

async function holdConnectionsDropped(sweep: () => Promise<number>): Promise<Actuation> {
    let terminated = await sweep()
    let failure: unknown
    const settled = Promise.withResolvers<void>()
    if (terminated > 0) {
        settled.resolve()
    }
    const released = new AbortController()
    const sweeping = (async () => {
        while (!released.signal.aborted) {
            await sleep(DROP_SWEEP_EVERY_MS, undefined, { signal: released.signal }).catch(() => undefined)
            if (released.signal.aborted) {
                return
            }
            try {
                terminated += await sweep()
            } catch (error) {
                failure = error
                settled.resolve()
                return
            }
            if (terminated > 0) {
                settled.resolve()
            }
        }
    })()
    return {
        async observed(holdEnds) {
            if (holdEnds !== undefined && !holdEnds.aborted) {
                await Promise.race([settled.promise, once(holdEnds, 'abort')])
            }
            return terminated > 0
        },
        async release() {
            released.abort()
            await sweeping
            if (failure !== undefined) {
                throw failure
            }
        },
    }
}

export function createEnvironment({
    hogli = { command: path.join(REPO_ROOT, 'bin', 'hogli'), cwd: REPO_ROOT },
    docker = 'docker',
    postgresUrl = STACK.postgresUrl,
    sesRateLimiterValkey = STACK.sesRateLimiterValkey,
    roleHealthyWithinMs = ROLE_HEALTHY_WITHIN_MS,
    aws,
    failover = {},
}: Partial<EnvironmentOptions> = {}): Environment {
    const env = process.env
    let stateDir = defaultStateDir(env)
    const secrets = secretsOf(env)
    const supervisor = createSupervisor({
        command: TSX,
        args: ['src/index.ts'],
        cwd: NODEJS_DIR,
        logDir: stateDir,
        graceMs: STOP_GRACE_MS,
        restartBackoffMs: ROLE_RESTART_BACKOFF_MS,
    })
    let edge: ProviderEdge | undefined
    let probing: { edgeUrl: string | undefined; probes: ProbeProcess } | undefined
    let postgresServers = [postgresUrl]
    let cyclotronUrl = STACK.cyclotronNodeUrl
    let releaseLock: (() => Promise<void>) | undefined
    let running: RoleId[] = roleIdsOf()

    const logOf = (id: RoleId): string => path.join(stateDir, `${nameOf(id)}.log`)

    return {
        async up(signal) {
            if (!existsSync(TSX)) {
                throw new Error(`No tsx at ${TSX}; install the nodejs package first.`)
            }
            mkdirSync(stateDir, { recursive: true })
            stateDir = realpathSync(stateDir)
            releaseLock = await holdRunLock(stateDir)
            try {
                await bringUp(signal)
            } catch (error) {
                await stop()
                throw error
            }
        },

        async reset(settings, replicas = {}) {
            const edge = startedEdge('reset')
            try {
                await resetRoles(edge, settings, replicas)
            } catch (error) {
                await stop()
                throw error
            }
        },

        edgeUrl: () => startedEdge('edgeUrl').url,

        role: (name) => handleOf({ role: name, replica: 0 }),

        roles: () => running.map(handleOf),

        async dependencyHealth() {
            if (!probing || probing.edgeUrl !== edge?.url) {
                probing?.probes.close()
                probing = {
                    edgeUrl: edge?.url,
                    probes: startProbeProcess({ edgeUrl: edge?.url, postgresUrl, sesValkey: sesRateLimiterValkey }),
                }
            }
            const down = await probing.probes.check()
            return { healthy: down.length === 0, down }
        },

        async actuate(action) {
            switch (action.kind) {
                case 'kill': {
                    const gone = supervisor.kill({ role: action.role, replica: 0 }, KILL_OBSERVED_WITHIN_MS)
                    gone.catch(() => undefined)
                    return { observed: () => gone, release: () => Promise.resolve() }
                }
                case 'freeze':
                    return supervisor.freeze({ role: action.role, replica: 0 }, FREEZE_OBSERVED_WITHIN_MS)
                case 'pg.terminate': {
                    const servers = postgresServers
                    return holdConnectionsDropped(async () => {
                        let terminated = 0
                        for (const server of servers) {
                            terminated += await terminateRoleConnections(server, action.share)
                        }
                        return terminated
                    })
                }
                case 'edge.fault':
                    return startedEdge('actuate').hold(action.rule)
                case 'rds.failover':
                    return failOver({
                        identity: () => sqlIdentityOf(cyclotronUrl),
                        ...failover,
                        aws: aws ?? awsCli(env),
                        manifest: action.manifest,
                        holdMs: action.holdMs,
                        commits: action.commits,
                        signal: action.signal,
                    })
            }
        },

        exits: (): RoleExit[] => supervisor.exits(),

        groupLag: (group) => groupLag(group, docker),

        async wiring(signal) {
            const clients = await Promise.all(postgresServers.map((server) => postgresClients(server)))
            return wiringOf({
                adapter: WORKFLOWS_ADAPTER,
                specs: running,
                groups: await kafkaGroups(docker, signal),
                clients: clients.flat(),
                recordedAt: new Date(),
            })
        },

        writerCpu: (manifest, window, signal) => writerCpuOf(aws ?? awsCli(env), manifest, window, signal),

        down: stop,
    }

    function startedEdge(caller: string): ProviderEdge {
        if (!edge) {
            throw new Error(`Start the environment with up() before ${caller}().`)
        }
        return edge
    }

    async function resetRoles(edge: ProviderEdge, settings: Profile['settings'], replicas: Replicas): Promise<void> {
        const exitsBefore = supervisor.exits().length
        const joined = await kafkaGroups(docker).then(scenarioGroupsOf, () => [])
        await supervisor.stop()
        const specs = roleSpecs(env, edge, secrets, stateDir, settings, sesRateLimiterValkey, replicas)
        running = specs
        await createTopics(intakeTopicsOf(specs), docker)
        const groups = unionOf(consumerGroupsOf(specs), joined)
        await waitForExpect(
            async () => {
                const busy = await groupsWithMembers(groups, docker)
                if (busy.length > 0) {
                    throw new Error(
                        `The consumer groups ${busy.join(', ')} still have members ${GROUPS_EMPTY_WITHIN_MS / 1000}s after the roles stopped.`
                    )
                }
            },
            GROUPS_EMPTY_WITHIN_MS,
            PROBE_INTERVAL_MS
        )
        edge.clearFaults()
        postgresServers = postgresServersOf(specs[0], postgresUrl)
        cyclotronUrl = cyclotronUrlOf(specs[0])
        await deleteUnfinishedJobs(cyclotronUrl)
        await forgetSesBucket(sesRateLimiterValkey)
        for (const group of groups) {
            await seekToEnd(group, docker)
        }
        await refuseHeldPorts(portsOf(specs))
        await supervisor.start(specs)
        await untilHealthy(specs, exitsBefore)
    }

    async function untilHealthy(specs: RoleSpec[], exitsBefore: number): Promise<void> {
        const deadline = Date.now() + roleHealthyWithinMs
        const names = specs.map(nameOf)
        for (;;) {
            const notReady = await rolesNotReady(specs)
            const exit = supervisor
                .exits()
                .slice(exitsBefore)
                .find((id) => names.includes(nameOf(id)))
            if (exit) {
                const how = exit.error ?? `code ${exit.code}, signal ${exit.signal}`
                throw new Error(
                    `${nameOf(exit)} exited while the runner waited for /_health (${how}); see ${logOf(exit)}`
                )
            }
            if (notReady.length === 0) {
                return
            }
            if (Date.now() > deadline) {
                throw new Error(
                    `${notReady.map(nameOf).join(', ')} did not answer /_health within ${roleHealthyWithinMs / 1000}s; see ${notReady.map(logOf).join(', ')}`
                )
            }
            await sleep(PROBE_INTERVAL_MS)
        }
    }

    async function refuseHeldPorts(wanted: { port: number; owner: string }[]): Promise<void> {
        const held = (
            await Promise.all(wanted.map(async (want) => ((await isPortFree(want.port)) ? [] : [want])))
        ).flat()
        if (held.length > 0) {
            const inspect = `ss -ltnp '${held.map(({ port }) => `sport = :${port}`).join(' or ')}'`
            const ports = held.map(({ port, owner }) => `${port} (${owner})`).join(', ')
            throw new StackConflictError(
                `Ports the runner needs are already held by processes it did not start: ${ports}. Find the processes that hold them with \`${inspect}\`, stop them, then run the scenario again.`
            )
        }
    }

    async function bringUp(signal: AbortSignal): Promise<void> {
        const exitsBefore = supervisor.exits().length
        const plan = planCleanup(readProcs(), process.pid, NODEJS_DIR, stateDir)
        if (plan.strangers.length > 0) {
            throw await strangerConflict(plan.strangers)
        }
        await terminate(plan, STOP_GRACE_MS)
        await startStack(hogli, stateDir, env, signal)
        const planned = roleSpecs(
            env,
            { url: `http://127.0.0.1:${EDGE_PORT}` },
            secrets,
            stateDir,
            {},
            sesRateLimiterValkey
        )
        await refuseHeldPorts([...portsOf(planned), EDGE])
        const groups = consumerGroupsOf(planned)
        await waitForExpect(
            async () => {
                const busy = await groupsWithMembers(groups, docker)
                if (busy.length > 0) {
                    throw new StackConflictError(
                        `The CDP consumer groups ${busy.join(', ')} have members the runner did not start. Run \`hogli down\`, then run the scenario again.`
                    )
                }
            },
            GROUP_DRAINS_WITHIN_MS,
            PROBE_INTERVAL_MS
        )
        edge = await startProviderEdge({
            port: EDGE_PORT,
            trackingKeys: secrets.encryptionSaltKeys,
            caDir: path.join(stateDir, 'edge-ca'),
            feedbackUrl: `http://127.0.0.1:${portOf({ role: 'cdp-api', replica: 0 })}/public/m/ses_webhook`,
        })
        const specs = roleSpecs(env, edge, secrets, stateDir, {}, sesRateLimiterValkey)
        running = specs
        await createTopics(intakeTopicsOf(specs), docker)
        for (const group of groups) {
            await seekToEnd(group, docker)
        }
        postgresServers = postgresServersOf(specs[0], postgresUrl)
        cyclotronUrl = cyclotronUrlOf(specs[0])
        const api = specs.filter((spec) => spec.role === 'cdp-api')
        const others = specs.filter((spec) => spec.role !== 'cdp-api')
        await supervisor.start(api)
        await untilHealthy(api, exitsBefore)
        if ((await missingTemplates(postgresUrl)).length > 0) {
            await syncTemplates(hogli, stateDir, env, signal)
        }
        await waitForExpect(
            async () => {
                const missing = await missingTemplates(postgresUrl)
                if (missing.length > 0) {
                    throw new Error(`Django has not synced the templates ${missing.join(', ')}.`)
                }
            },
            TEMPLATES_WITHIN_MS,
            PROBE_INTERVAL_MS
        )
        await supervisor.start(others)
        await untilHealthy(specs, exitsBefore)
    }

    async function stop(): Promise<void> {
        try {
            await supervisor.stop()
        } finally {
            probing?.probes.close()
            probing = undefined
            await edge?.close()
            edge = undefined
            await releaseLock?.()
            releaseLock = undefined
        }
    }
}
