import { existsSync, mkdirSync, realpathSync } from 'fs'
import os from 'os'
import path from 'path'

import { waitForExpect } from '~/tests/helpers/expectations'

import { Profile, ROLE_RESTART_BACKOFF_MS } from '../cards'
import { ProviderEdge, startProviderEdge } from '../provider-edge'
import { StackConflictError, holdRunLock, planCleanup, readProcs, strangerConflict, terminate } from './processes'
import { ConsumerGroup, ROLE_PORTS, Role, consumerGroupsOf, roleSpecs, secretsOf } from './roles'
import {
    cyclotronUrlOf,
    deleteUnfinishedJobs,
    downServices,
    expectOk,
    groupMembers,
    missingTemplates,
    rolesNotReady,
    seekToEnd,
    startStack,
    syncTemplates,
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

const NODEJS_DIR = realpathSync(path.resolve(__dirname, '..', '..', '..'))
const REPO_ROOT = path.dirname(NODEJS_DIR)
const TSX = path.join(NODEJS_DIR, 'node_modules', '.bin', 'tsx')
const EDGE_PORT = 4566
const TEMPLATES_WITHIN_MS = 120_000
const GROUP_DRAINS_WITHIN_MS = 60_000
const GROUPS_EMPTY_WITHIN_MS = 45_000
const ROLES_READY_WITHIN_MS = 120_000
const STOP_GRACE_MS = 10_000
const PROBE_INTERVAL_MS = 1000

export function defaultStateDir(env: NodeJS.ProcessEnv): string {
    return path.join(env.XDG_CACHE_HOME || path.join(os.homedir(), '.cache'), 'posthog-scenarios')
}

async function groupsWithMembers(groups: ConsumerGroup[]): Promise<string[]> {
    const members = await Promise.all(groups.map(({ group }) => groupMembers(group)))
    return groups.filter((_, i) => members[i] > 0).map(({ group }) => group)
}

export function createEnvironment(): Environment {
    const env = process.env
    const stateDir = defaultStateDir(env)
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
    let releaseLock: (() => void) | undefined

    return {
        async up() {
            if (!existsSync(TSX)) {
                throw new Error(`No tsx at ${TSX}; install the nodejs package first.`)
            }
            mkdirSync(stateDir, { recursive: true })
            releaseLock = holdRunLock(stateDir)
            const plan = planCleanup(readProcs(), process.pid, NODEJS_DIR)
            if (plan.strangers.length > 0) {
                throw strangerConflict(plan.strangers)
            }
            await terminate(plan, STOP_GRACE_MS)
            await startStack(REPO_ROOT, stateDir, env)
            const specs = roleSpecs(env, `http://127.0.0.1:${EDGE_PORT}`, secrets)
            const groups = consumerGroupsOf(specs)
            const killedLeftovers = plan.groups.length + plan.pids.length > 0
            await waitForExpect(
                async () => {
                    const busy = await groupsWithMembers(groups)
                    if (busy.length > 0) {
                        throw new StackConflictError(
                            `The CDP consumer groups ${busy.join(', ')} have members the runner did not start.`,
                            'hogli down'
                        )
                    }
                },
                killedLeftovers ? GROUP_DRAINS_WITHIN_MS : 0,
                PROBE_INTERVAL_MS
            )
            edge = await startProviderEdge({ port: EDGE_PORT, trackingKeys: secrets.encryptionSaltKeys })
            await supervisor.start(specs.filter((spec) => spec.role === 'cdp-api'))
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
            await supervisor.start(specs.filter((spec) => spec.role !== 'cdp-api'))
        },

        async reset(settings) {
            if (!edge) {
                throw new Error('Start the environment with up() before reset().')
            }
            await supervisor.stop()
            const specs = roleSpecs(env, edge.url, secrets, settings)
            const groups = consumerGroupsOf(specs)
            await waitForExpect(
                async () => {
                    const busy = await groupsWithMembers(groups)
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
            await Promise.all([...new Set(specs.map(cyclotronUrlOf))].map(deleteUnfinishedJobs))
            for (const group of groups) {
                await seekToEnd(group)
            }
            await supervisor.start(specs)
            await waitForExpect(
                async () => {
                    const notReady = await rolesNotReady(specs)
                    if (notReady.length > 0) {
                        throw new Error(
                            `The roles ${notReady.join(', ')} did not answer /_health within ${ROLES_READY_WITHIN_MS / 1000}s.`
                        )
                    }
                },
                ROLES_READY_WITHIN_MS,
                PROBE_INTERVAL_MS
            )
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
            releaseLock?.()
            releaseLock = undefined
        },
    }
}
