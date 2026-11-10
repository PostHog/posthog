import { existsSync, mkdirSync } from 'fs'
import os from 'os'
import path from 'path'

import { Profile, ROLE_RESTART_BACKOFF_MS } from '../cards'
import { ProviderEdge, startProviderEdge } from '../provider-edge'
import { StackConflictError, planCleanup, readProcs, strangerConflict, terminate } from './processes'
import { ROLE_PORTS, Role, consumerGroupsOf, roleSpecs, secretsOf } from './roles'
import {
    STACK,
    cyclotronUrlOf,
    deleteUnfinishedJobs,
    downServices,
    groupMembers,
    missingTemplates,
    poll,
    rolesNotReady,
    seekToEnd,
    startStack,
} from './stack'
import { RoleExit, createSupervisor } from './supervisor'

export type { RoleExit } from './supervisor'

export interface Environment {
    up(): Promise<void>
    reset(settings: Profile['settings']): Promise<void>
    role(name: Role): RoleHandle
    health(): Promise<{ healthy: boolean; down: string[] }>
    exits(): RoleExit[]
    down(): Promise<void>
}

export type RoleHandle = { name: Role; metricsUrl: string }

export type EnvironmentOptions = {
    repoRoot?: string
    stateDir?: string
    env?: NodeJS.ProcessEnv
    edgePort?: number
    templatesWithinMs?: number
    groupDrainsWithinMs?: number
    groupsEmptyWithinMs?: number
    rolesReadyWithinMs?: number
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
    const supervisor = createSupervisor({
        command: TSX,
        args: ['src/index.ts'],
        cwd: NODEJS_DIR,
        logDir: stateDir,
        graceMs: stopGraceMs,
        restartBackoffMs: ROLE_RESTART_BACKOFF_MS,
    })
    let edge: ProviderEdge | undefined

    return {
        async up() {
            if (!existsSync(TSX)) {
                throw new Error(`No tsx at ${TSX}; install the nodejs package first.`)
            }
            mkdirSync(stateDir, { recursive: true })
            const plan = planCleanup(readProcs(), process.pid)
            if (plan.strangers.length > 0) {
                throw strangerConflict(plan.strangers)
            }
            await terminate(plan, stopGraceMs)
            await startStack(repoRoot, stateDir, env)
            const killedLeftovers = plan.groups.length + plan.pids.length > 0
            const drained = await poll(
                async () => ((await groupMembers(STACK.eventsConsumerGroup)) === 0 ? true : undefined),
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
            await supervisor.start(roleSpecs(env, edge.url, secrets))
        },

        async reset(settings) {
            if (!edge) {
                throw new Error('Start the environment with up() before reset().')
            }
            await supervisor.stop()
            const specs = roleSpecs(env, edge.url, secrets, settings)
            const groups = consumerGroupsOf(specs)
            const withMembers = async (): Promise<string[]> => {
                const members = await Promise.all(groups.map(({ group }) => groupMembers(group)))
                return groups.filter((_, i) => members[i] > 0).map(({ group }) => group)
            }
            const groupsWithinMs = options.groupsEmptyWithinMs ?? 45_000
            if (!(await poll(async () => ((await withMembers()).length === 0 ? true : undefined), groupsWithinMs))) {
                throw new Error(
                    `The consumer groups ${(await withMembers()).join(', ')} still have members ${groupsWithinMs / 1000}s after the roles stopped.`
                )
            }
            edge.clearFaults()
            await Promise.all([...new Set(specs.map(cyclotronUrlOf))].map(deleteUnfinishedJobs))
            for (const group of groups) {
                await seekToEnd(group)
            }
            await supervisor.start(specs)
            const readyWithinMs = options.rolesReadyWithinMs ?? 120_000
            if (
                !(await poll(async () => ((await rolesNotReady(specs)).length === 0 ? true : undefined), readyWithinMs))
            ) {
                throw new Error(
                    `The roles ${(await rolesNotReady(specs)).join(', ')} did not answer /_health within ${readyWithinMs / 1000}s.`
                )
            }
        },

        role: (name) => ({ name, metricsUrl: `http://127.0.0.1:${ROLE_PORTS[name]}/_metrics` }),

        async health() {
            const down = await downServices(edge?.url)
            return { healthy: down.length === 0, down }
        },

        exits: (): RoleExit[] => supervisor.exits(),

        async down() {
            await supervisor.stop()
            await edge?.close()
            edge = undefined
        },
    }
}
