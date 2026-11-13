import { existsSync, mkdirSync, realpathSync } from 'fs'
import os from 'os'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'

import { waitForExpect } from '~/tests/helpers/expectations'
import { isPortFree } from '~/tests/helpers/service-process'

import { Profile, ROLE_RESTART_BACKOFF_MS } from '../cards'
import { ProviderEdge, startProviderEdge } from '../provider-edge'
import { StackConflictError, holdRunLock, planCleanup, readProcs, strangerConflict, terminate } from './processes'
import { ConsumerGroup, ROLE_PORTS, Role, RoleSpec, consumerGroupsOf, roleSpecs, secretsOf } from './roles'
import {
    Hogli,
    STACK,
    cyclotronUrlOf,
    deleteUnfinishedJobs,
    downServices,
    forgetSesBucket,
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

export type { RoleExit } from './supervisor'

export interface Environment {
    up(): Promise<void>
    reset(settings: Profile['settings']): Promise<void>
    edgeUrl(): string
    role(name: Role): RoleHandle
    actuate(action: Action): Promise<Actuation>
    dependencyHealth(): Promise<{ healthy: boolean; down: string[] }>
    exits(): RoleExit[]
    down(): Promise<void>
}

export type RoleHandle = { name: Role; url: string; metricsUrl: string }

export type Action =
    | { kind: 'kill'; role: Role }
    | { kind: 'freeze'; role: Role }
    | { kind: 'pg.terminate'; share: number }

export type Actuation = { observed(): Promise<boolean>; release(): Promise<void> }

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

const portsOf = (specs: RoleSpec[]): { port: number; owner: string }[] =>
    specs.map(({ role }) => ({ port: ROLE_PORTS[role], owner: role }))

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
}

export function createEnvironment({
    hogli = { command: path.join(REPO_ROOT, 'bin', 'hogli'), cwd: REPO_ROOT },
    docker = 'docker',
    postgresUrl = STACK.postgresUrl,
    sesRateLimiterValkey = STACK.sesRateLimiterValkey,
    roleHealthyWithinMs = ROLE_HEALTHY_WITHIN_MS,
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
    let postgresServers = [postgresUrl]
    let releaseLock: (() => Promise<void>) | undefined

    const logOf = (role: Role): string => path.join(stateDir, `${role}.log`)

    return {
        async up() {
            if (!existsSync(TSX)) {
                throw new Error(`No tsx at ${TSX}; install the nodejs package first.`)
            }
            mkdirSync(stateDir, { recursive: true })
            stateDir = realpathSync(stateDir)
            releaseLock = await holdRunLock(stateDir)
            try {
                await bringUp()
            } catch (error) {
                await stop()
                throw error
            }
        },

        async reset(settings) {
            const edge = startedEdge('reset')
            try {
                await resetRoles(edge, settings)
            } catch (error) {
                await stop()
                throw error
            }
        },

        edgeUrl: () => startedEdge('edgeUrl').url,

        role: (name) => ({
            name,
            url: `http://127.0.0.1:${ROLE_PORTS[name]}`,
            metricsUrl: `http://127.0.0.1:${ROLE_PORTS[name]}/_metrics`,
        }),

        async dependencyHealth() {
            const down = await downServices(edge?.url, postgresUrl, sesRateLimiterValkey)
            return { healthy: down.length === 0, down }
        },

        async actuate(action) {
            switch (action.kind) {
                case 'kill': {
                    const gone = supervisor.kill(action.role, KILL_OBSERVED_WITHIN_MS)
                    gone.catch(() => undefined)
                    return { observed: () => gone, release: () => Promise.resolve() }
                }
                case 'freeze':
                    return supervisor.freeze(action.role, FREEZE_OBSERVED_WITHIN_MS)
                case 'pg.terminate': {
                    let terminated = 0
                    for (const server of postgresServers) {
                        terminated += await terminateRoleConnections(server, action.share)
                    }
                    return { observed: () => Promise.resolve(terminated > 0), release: () => Promise.resolve() }
                }
            }
        },

        exits: (): RoleExit[] => supervisor.exits(),

        down: stop,
    }

    function startedEdge(caller: string): ProviderEdge {
        if (!edge) {
            throw new Error(`Start the environment with up() before ${caller}().`)
        }
        return edge
    }

    async function resetRoles(edge: ProviderEdge, settings: Profile['settings']): Promise<void> {
        const exitsBefore = supervisor.exits().length
        await supervisor.stop()
        const specs = roleSpecs(env, edge, secrets, stateDir, settings, sesRateLimiterValkey)
        const groups = consumerGroupsOf(specs)
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
        await deleteUnfinishedJobs(cyclotronUrlOf(specs[0]))
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
        const roles = specs.map((spec) => spec.role)
        for (;;) {
            const notReady = await rolesNotReady(specs)
            const exit = supervisor
                .exits()
                .slice(exitsBefore)
                .find(({ role }) => roles.includes(role))
            if (exit) {
                const how = exit.error ?? `code ${exit.code}, signal ${exit.signal}`
                throw new Error(
                    `${exit.role} exited while the runner waited for /_health (${how}); see ${logOf(exit.role)}`
                )
            }
            if (notReady.length === 0) {
                return
            }
            if (Date.now() > deadline) {
                throw new Error(
                    `${notReady.join(', ')} did not answer /_health within ${roleHealthyWithinMs / 1000}s; see ${notReady.map(logOf).join(', ')}`
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

    async function bringUp(): Promise<void> {
        const exitsBefore = supervisor.exits().length
        const plan = planCleanup(readProcs(), process.pid, NODEJS_DIR, stateDir)
        if (plan.strangers.length > 0) {
            throw await strangerConflict(plan.strangers)
        }
        await terminate(plan, STOP_GRACE_MS)
        await startStack(hogli, stateDir, env)
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
        })
        const specs = roleSpecs(env, edge, secrets, stateDir, {}, sesRateLimiterValkey)
        postgresServers = postgresServersOf(specs[0], postgresUrl)
        const api = specs.filter((spec) => spec.role === 'cdp-api')
        const others = specs.filter((spec) => spec.role !== 'cdp-api')
        await supervisor.start(api)
        await untilHealthy(api, exitsBefore)
        if ((await missingTemplates(postgresUrl)).length > 0) {
            await syncTemplates(hogli, stateDir, env)
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
            await edge?.close()
            edge = undefined
            await releaseLock?.()
            releaseLock = undefined
        }
    }
}
