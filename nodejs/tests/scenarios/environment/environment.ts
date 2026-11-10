import { ChildProcess, spawn } from 'child_process'
import { closeSync, existsSync, mkdirSync, openSync, realpathSync } from 'fs'
import os from 'os'
import path from 'path'

import { waitForExpect } from '~/tests/helpers/expectations'

import { ROLE_RESTART_BACKOFF_MS } from '../cards'
import { ProviderEdge, startProviderEdge } from '../provider-edge'
import { StackConflictError, holdRunLock, planCleanup, readProcs, strangerConflict, terminate } from './processes'
import { ROLE_PORTS, Role, RoleSpec, roleSpecs, secretsOf } from './roles'
import {
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

export type RoleExit = { role: Role; at: string; code: number | null; signal: string | null; byValve: boolean }

const NODEJS_DIR = realpathSync(path.resolve(__dirname, '..', '..', '..'))
const REPO_ROOT = path.dirname(NODEJS_DIR)
const TSX = path.join(NODEJS_DIR, 'node_modules', '.bin', 'tsx')
const EDGE_PORT = 4566
const TEMPLATES_WITHIN_MS = 120_000
const GROUP_DRAINS_WITHIN_MS = 60_000
const STOP_GRACE_MS = 10_000
const PROBE_INTERVAL_MS = 1000

export function defaultStateDir(env: NodeJS.ProcessEnv): string {
    return path.join(env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache'), 'posthog-scenarios')
}

export function createEnvironment(): Environment {
    const env = process.env
    const stateDir = defaultStateDir(env)
    const secrets = secretsOf(env)
    const children = new Map<Role, ChildProcess>()
    const restarts = new Set<NodeJS.Timeout>()
    const recorded: RoleExit[] = []
    let edge: ProviderEdge | undefined
    let releaseLock: (() => void) | undefined
    let stopping = false

    const start = (spec: RoleSpec): void => {
        const log = openSync(path.join(stateDir, `${spec.role}.log`), 'a')
        const child = spawn(TSX, ['src/index.ts'], {
            cwd: NODEJS_DIR,
            env: spec.env,
            detached: true,
            stdio: ['ignore', log, log],
        })
        closeSync(log)
        children.set(spec.role, child)
        child.once('exit', (code, signal) => {
            if (stopping) {
                return
            }
            void terminate({ groups: child.pid ? [child.pid] : [], pids: [] }, 0)
            recorded.push({ role: spec.role, at: new Date().toISOString(), code, signal, byValve: false })
            const restart = setTimeout(() => {
                restarts.delete(restart)
                if (!stopping) {
                    start(spec)
                }
            }, ROLE_RESTART_BACKOFF_MS)
            restarts.add(restart)
        })
    }

    return {
        async up() {
            if (!existsSync(TSX)) {
                throw new Error(`No tsx at ${TSX}; install the nodejs package first.`)
            }
            mkdirSync(stateDir, { recursive: true })
            releaseLock = holdRunLock(stateDir)
            stopping = false
            const plan = planCleanup(readProcs(), process.pid, NODEJS_DIR)
            if (plan.strangers.length > 0) {
                throw strangerConflict(plan.strangers)
            }
            await terminate(plan, STOP_GRACE_MS)
            await startStack(REPO_ROOT, stateDir, env)
            const specs = roleSpecs(env, `http://127.0.0.1:${EDGE_PORT}`, secrets)
            const group = eventsConsumerGroup(specs)
            const killedLeftovers = plan.groups.length + plan.pids.length > 0
            await waitForExpect(
                async () => {
                    if ((await groupMembers(group)) > 0) {
                        throw new StackConflictError(
                            `The CDP events consumer group ${group} has a member the runner did not start.`,
                            'hogli down'
                        )
                    }
                },
                killedLeftovers ? GROUP_DRAINS_WITHIN_MS : 0,
                PROBE_INTERVAL_MS
            )
            edge = await startProviderEdge({ port: EDGE_PORT, trackingKeys: secrets.encryptionSaltKeys })
            specs.filter((spec) => spec.role === 'cdp-api').forEach(start)
            await waitForExpect(
                () => expectOk(`http://127.0.0.1:${ROLE_PORTS['cdp-api']}/_health`),
                TEMPLATES_WITHIN_MS,
                PROBE_INTERVAL_MS
            )
            if ((await missingTemplates()).length > 0) {
                await syncTemplates(REPO_ROOT, stateDir, env)
            }
            await waitForExpect(
                async () => {
                    const missing = await missingTemplates()
                    if (missing.length > 0) {
                        throw new Error(`Django has not synced the templates ${missing.join(', ')}.`)
                    }
                },
                TEMPLATES_WITHIN_MS,
                PROBE_INTERVAL_MS
            )
            specs.filter((spec) => spec.role !== 'cdp-api').forEach(start)
        },

        role: (name) => ({ name, metricsUrl: `http://127.0.0.1:${ROLE_PORTS[name]}/_metrics` }),

        async health() {
            const down = await downServices(edge?.url)
            return { healthy: down.length === 0, down }
        },

        exits: () => [...recorded],

        async down() {
            stopping = true
            restarts.forEach(clearTimeout)
            restarts.clear()
            const groups = [...children.values()].flatMap((child) => (child.pid ? [child.pid] : []))
            children.clear()
            await terminate({ groups, pids: [] }, STOP_GRACE_MS)
            await edge?.close()
            edge = undefined
            releaseLock?.()
            releaseLock = undefined
        },
    }
}
