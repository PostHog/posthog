import { ChildProcess, spawn } from 'child_process'
import { closeSync, existsSync, mkdirSync, openSync, realpathSync } from 'fs'
import os from 'os'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'

import { waitForExpect } from '~/tests/helpers/expectations'
import { isPortFree } from '~/tests/helpers/service-process'

import { ROLE_RESTART_BACKOFF_MS } from '../cards'
import { ProviderEdge, startProviderEdge } from '../provider-edge'
import { StackConflictError, holdRunLock, planCleanup, readProcs, strangerConflict, terminate } from './processes'
import { ROLE_PORTS, Role, RoleSpec, roleSpecs, secretsOf } from './roles'
import {
    Hogli,
    STACK,
    downServices,
    eventsConsumerGroup,
    expectOk,
    groupMembers,
    missingTemplates,
    startStack,
    syncTemplates,
} from './stack'

export interface Environment {
    up(): Promise<void>
    role(name: Role): RoleHandle
    health(): Promise<{ healthy: boolean; down: string[] }>
    exits(): RoleExit[]
    down(): Promise<void>
}

export type RoleHandle = { name: Role; metricsUrl: string }

export type RoleExit = {
    role: Role
    at: string
    code: number | null
    signal: string | null
    byValve: boolean
    error?: string
}

const NODEJS_DIR = realpathSync(path.resolve(__dirname, '..', '..', '..'))
const REPO_ROOT = path.dirname(NODEJS_DIR)
const TSX = path.join(NODEJS_DIR, 'node_modules', '.bin', 'tsx')
const EDGE_PORT = 4566
const TEMPLATES_WITHIN_MS = 120_000
const ROLE_HEALTHY_WITHIN_MS = 120_000
const GROUP_DRAINS_WITHIN_MS = 60_000
const STOP_GRACE_MS = 10_000
const PROBE_INTERVAL_MS = 1000

export function defaultStateDir(env: NodeJS.ProcessEnv): string {
    return path.join(env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache'), 'posthog-scenarios')
}

export type EnvironmentOptions = { hogli: Hogli; docker: string; postgresUrl: string }

export function createEnvironment({
    hogli = { command: path.join(REPO_ROOT, 'bin', 'hogli'), cwd: REPO_ROOT },
    docker = 'docker',
    postgresUrl = STACK.postgresUrl,
}: Partial<EnvironmentOptions> = {}): Environment {
    const env = process.env
    const stateDir = defaultStateDir(env)
    const secrets = secretsOf(env)
    const children = new Map<Role, ChildProcess>()
    const restarts = new Set<NodeJS.Timeout>()
    const recorded: RoleExit[] = []
    let edge: ProviderEdge | undefined
    let releaseLock: (() => Promise<void>) | undefined
    let stopping = false

    const logOf = (role: Role): string => path.join(stateDir, `${role}.log`)

    const recordAndRestart = (spec: RoleSpec, exit: Pick<RoleExit, 'code' | 'signal' | 'error'>): void => {
        recorded.push({ role: spec.role, at: new Date().toISOString(), byValve: false, ...exit })
        const restart = setTimeout(() => {
            restarts.delete(restart)
            if (!stopping) {
                start(spec)
            }
        }, ROLE_RESTART_BACKOFF_MS)
        restarts.add(restart)
    }

    const start = (spec: RoleSpec): void => {
        const log = openSync(logOf(spec.role), 'a')
        const child = spawn(TSX, ['src/index.ts'], {
            cwd: NODEJS_DIR,
            env: spec.env,
            detached: true,
            stdio: ['ignore', log, log],
        })
        closeSync(log)
        children.set(spec.role, child)
        child.once('error', (error) => {
            if (stopping || child.pid !== undefined) {
                return
            }
            recordAndRestart(spec, { code: null, signal: null, error: error.message })
        })
        child.once('exit', (code, signal) => {
            if (stopping) {
                return
            }
            void terminate({ groups: child.pid ? [child.pid] : [], pids: [] }, 0)
            recordAndRestart(spec, { code, signal })
        })
    }

    return {
        async up() {
            if (!existsSync(TSX)) {
                throw new Error(`No tsx at ${TSX}; install the nodejs package first.`)
            }
            mkdirSync(stateDir, { recursive: true })
            releaseLock = await holdRunLock(stateDir)
            stopping = false
            try {
                await bringUp()
            } catch (error) {
                await stop()
                throw error
            }
        },

        role: (name) => ({ name, metricsUrl: `http://127.0.0.1:${ROLE_PORTS[name]}/_metrics` }),

        async health() {
            const down = await downServices(edge?.url, postgresUrl)
            return { healthy: down.length === 0, down }
        },

        exits: () => [...recorded],

        down: stop,
    }

    async function untilHealthy(roles: Role[], exitsBefore: number): Promise<void> {
        const deadline = Date.now() + ROLE_HEALTHY_WITHIN_MS
        for (;;) {
            const answering = await Promise.all(roles.map(answersHealth))
            const exit = recorded.slice(exitsBefore).find((exit) => roles.includes(exit.role))
            if (exit) {
                const how = exit.error ?? `code ${exit.code}, signal ${exit.signal}`
                throw new Error(`${exit.role} exited while up waited for /_health (${how}); see ${logOf(exit.role)}`)
            }
            const silent = roles.find((_role, index) => !answering[index])
            if (silent === undefined) {
                return
            }
            if (Date.now() > deadline) {
                throw new Error(
                    `${silent} did not answer /_health within ${ROLE_HEALTHY_WITHIN_MS / 1000}s; see ${logOf(silent)}`
                )
            }
            await sleep(PROBE_INTERVAL_MS)
        }
    }

    async function refuseHeldPorts(roles: Role[]): Promise<void> {
        const held = (
            await Promise.all(roles.map(async (role) => ((await isPortFree(ROLE_PORTS[role])) ? [] : [role])))
        ).flat()
        if (held.length > 0) {
            const inspect = `ss -ltnp '${held.map((role) => `sport = :${ROLE_PORTS[role]}`).join(' or ')}'`
            const ports = held.map((role) => `${ROLE_PORTS[role]} (${role})`).join(', ')
            throw new StackConflictError(
                `Role ports are already held by processes the runner did not start: ${ports}. Find the processes that hold them with \`${inspect}\`, stop them, then run the scenario again.`
            )
        }
    }

    async function bringUp(): Promise<void> {
        const exitsBefore = recorded.length
        const plan = planCleanup(readProcs(), process.pid, NODEJS_DIR)
        if (plan.strangers.length > 0) {
            throw strangerConflict(plan.strangers)
        }
        await terminate(plan, STOP_GRACE_MS)
        await startStack(hogli, stateDir, env)
        const specs = roleSpecs(env, `http://127.0.0.1:${EDGE_PORT}`, secrets)
        await refuseHeldPorts(specs.map((spec) => spec.role))
        const group = eventsConsumerGroup(specs)
        await waitForExpect(
            async () => {
                if ((await groupMembers(group, docker)) > 0) {
                    throw new StackConflictError(
                        `The CDP events consumer group ${group} has a member the runner did not start. Run \`hogli down\`, then run the scenario again.`
                    )
                }
            },
            GROUP_DRAINS_WITHIN_MS,
            PROBE_INTERVAL_MS
        )
        edge = await startProviderEdge({ port: EDGE_PORT, trackingKeys: secrets.encryptionSaltKeys })
        const others = specs.filter((spec) => spec.role !== 'cdp-api')
        specs.filter((spec) => spec.role === 'cdp-api').forEach(start)
        await untilHealthy(['cdp-api'], exitsBefore)
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
        others.forEach(start)
        await untilHealthy(
            specs.map((spec) => spec.role),
            exitsBefore
        )
    }

    async function answersHealth(role: Role): Promise<boolean> {
        return await expectOk(`http://127.0.0.1:${ROLE_PORTS[role]}/_health`).then(
            () => true,
            () => false
        )
    }

    async function stop(): Promise<void> {
        stopping = true
        restarts.forEach(clearTimeout)
        restarts.clear()
        const groups = [...children.values()].flatMap((child) => (child.pid ? [child.pid] : []))
        children.clear()
        await terminate({ groups, pids: [] }, STOP_GRACE_MS)
        await edge?.close()
        edge = undefined
        await releaseLock?.()
        releaseLock = undefined
    }
}
