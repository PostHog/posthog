import { ChildProcess, spawn } from 'child_process'
import { closeSync, existsSync, mkdirSync, openSync } from 'fs'
import os from 'os'
import path from 'path'

import { ROLE_RESTART_BACKOFF_MS } from '../cards'
import { ProviderEdge, startProviderEdge } from '../provider-edge'
import { StackConflictError, planCleanup, readProcs, strangerConflict, terminate } from './processes'
import { ROLE_PORTS, Role, RoleSpec, roleSpecs, secretsOf } from './roles'
import { STACK, downServices, eventsGroupMembers, missingTemplates, poll, startStack } from './stack'

export interface Environment {
    up(): Promise<void>
    role(name: Role): RoleHandle
    health(): Promise<{ healthy: boolean; down: string[] }>
    exits(): RoleExit[]
    down(): Promise<void>
}

export type RoleHandle = { name: Role; metricsUrl: string }

export type RoleExit = { role: Role; at: string; code: number | null; signal: string | null; byValve: boolean }

export type EnvironmentOptions = {
    repoRoot?: string
    stateDir?: string
    env?: NodeJS.ProcessEnv
    edgePort?: number
    templatesWithinMs?: number
    groupDrainsWithinMs?: number
    stopGraceMs?: number
}

const NODEJS_DIR = path.resolve(__dirname, '..', '..', '..')
const TSX = path.join(NODEJS_DIR, 'node_modules', '.bin', 'tsx')

export function defaultStateDir(env: NodeJS.ProcessEnv): string {
    return path.join(env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache'), 'posthog-scenarios')
}

export function createEnvironment(options: EnvironmentOptions = {}): Environment {
    const env = options.env ?? process.env
    const repoRoot = options.repoRoot ?? path.dirname(NODEJS_DIR)
    const stateDir = options.stateDir ?? defaultStateDir(env)
    const stopGraceMs = options.stopGraceMs ?? 10_000
    const secrets = secretsOf(env)
    const children = new Map<Role, ChildProcess>()
    const restarts = new Set<NodeJS.Timeout>()
    const recorded: RoleExit[] = []
    let edge: ProviderEdge | undefined
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
            stopping = false
            const plan = planCleanup(readProcs(), process.pid)
            if (plan.strangers.length > 0) {
                throw strangerConflict(plan.strangers)
            }
            await terminate(plan, stopGraceMs)
            await startStack(repoRoot, stateDir, env)
            const killedLeftovers = plan.groups.length + plan.pids.length > 0
            const drained = await poll(
                async () => ((await eventsGroupMembers()) === 0 ? true : undefined),
                killedLeftovers ? (options.groupDrainsWithinMs ?? 60_000) : 0
            )
            if (!drained) {
                throw new StackConflictError(
                    `The CDP events consumer group ${STACK.eventsConsumerGroup} has a member the runner did not start.`,
                    'hogli down'
                )
            }
            const templates = await poll(
                async () => ((await missingTemplates()).length === 0 ? true : undefined),
                options.templatesWithinMs ?? 120_000
            )
            if (!templates) {
                throw new Error(`Django has not synced the templates ${(await missingTemplates()).join(', ')}.`)
            }
            edge = await startProviderEdge({ port: options.edgePort ?? 4566, trackingKeys: secrets.encryptionSaltKeys })
            roleSpecs(env, edge.url, secrets).forEach(start)
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
            await terminate({ groups, pids: [] }, stopGraceMs)
            await edge?.close()
            edge = undefined
        },
    }
}
