import { ChildProcess, spawn } from 'child_process'
import { once } from 'events'
import { closeSync, openSync } from 'fs'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'

import { nameOf } from './identity'
import { processState, signal, terminate } from './processes'
import { RoleId, RoleSpec } from './roles'

const EXIT_REPORTED_WITHIN_MS = 2000
const STATE_POLL_MS = 20

const isRunning = (child: ChildProcess): boolean => child.exitCode === null && child.signalCode === null

const EXITED_STATES = [null, 'Z', 'X']

export type RoleExit = RoleId & {
    at: string
    code: number | null
    signal: string | null
    byValve: boolean
    error?: string
}

export type SupervisorOptions = {
    command: string
    args: string[]
    cwd: string
    logDir: string
    graceMs: number
    restartBackoffMs: number
}

export type Supervisor = {
    start(specs: RoleSpec[]): Promise<void>
    stop(): Promise<void>
    kill(id: RoleId, withinMs: number): Promise<boolean>
    freeze(id: RoleId, withinMs: number): { observed(): Promise<boolean>; release(): Promise<void> }
    exits(): RoleExit[]
}

export function createSupervisor(options: SupervisorOptions): Supervisor {
    const children = new Map<string, ChildProcess>()
    const restarts = new Set<NodeJS.Timeout>()
    const recorded: RoleExit[] = []
    const killedByValve = new WeakSet<ChildProcess>()
    let stopping = false

    const runningChild = (id: RoleId): ChildProcess & { pid: number } => {
        const child = children.get(nameOf(id))
        if (child?.pid === undefined || !isRunning(child) || EXITED_STATES.includes(processState(child.pid))) {
            throw new Error(`${nameOf(id)} is not running`)
        }
        return child as ChildProcess & { pid: number }
    }

    const relaunchLater = (spec: RoleSpec): void => {
        const restart = setTimeout(() => {
            restarts.delete(restart)
            if (!stopping) {
                launch(spec)
            }
        }, options.restartBackoffMs)
        restarts.add(restart)
    }

    const launch = (spec: RoleSpec): ChildProcess => {
        const name = nameOf(spec)
        const log = openSync(path.join(options.logDir, `${name}.log`), 'a')
        const child = spawn(options.command, options.args, {
            cwd: options.cwd,
            env: spec.env,
            detached: true,
            stdio: ['ignore', log, log],
        })
        closeSync(log)
        children.set(name, child)
        child.once('error', (error) => {
            if (children.get(name) === child) {
                children.delete(name)
            }
            if (stopping || child.pid !== undefined) {
                return
            }
            recorded.push({
                role: spec.role,
                replica: spec.replica,
                at: new Date().toISOString(),
                code: null,
                signal: null,
                byValve: false,
                error: error.message,
            })
            relaunchLater(spec)
        })
        child.once('exit', (code, signal) => {
            if (children.get(name) === child) {
                children.delete(name)
            }
            if (stopping) {
                return
            }
            void terminate({ groups: child.pid ? [child.pid] : [], pids: [] }, 0)
            recorded.push({
                role: spec.role,
                replica: spec.replica,
                at: new Date().toISOString(),
                code,
                signal,
                byValve: killedByValve.has(child) && signal === 'SIGKILL',
            })
            relaunchLater(spec)
        })
        return child
    }

    return {
        async start(specs) {
            stopping = false
            await Promise.all(specs.map((spec) => once(launch(spec), 'spawn').catch(() => undefined)))
        },

        async stop() {
            stopping = true
            restarts.forEach(clearTimeout)
            restarts.clear()
            const running = [...children.entries()]
            children.clear()
            const exited = running.filter(([, child]) => isRunning(child)).map(([, child]) => once(child, 'exit'))
            await terminate(
                { groups: running.flatMap(([, child]) => (child.pid ? [child.pid] : [])), pids: [] },
                options.graceMs
            )
            await Promise.race([Promise.all(exited), sleep(EXIT_REPORTED_WITHIN_MS, undefined, { ref: false })])
            const survivors = running.filter(([, child]) => isRunning(child))
            if (survivors.length > 0) {
                throw new Error(
                    `${survivors.map(([role, child]) => `${role} (pid ${child.pid})`).join(', ')} did not exit after SIGKILL; a process stuck in uninterruptible I/O can outlive it. Check them with \`ps -o pid,stat,cmd -p ${survivors.map(([, child]) => child.pid).join(',')}\` and wait for them to exit, then run the scenario again.`
                )
            }
        },

        async kill(id, withinMs) {
            const child = runningChild(id)
            killedByValve.add(child)
            const exited = once(child, 'exit').then(([, signal]) => signal === 'SIGKILL')
            process.kill(-child.pid, 'SIGKILL')
            const gaveUp = new AbortController()
            const outcome = await Promise.race([
                exited,
                sleep(withinMs, false, { signal: gaveUp.signal }).catch(() => false),
            ])
            gaveUp.abort()
            return outcome
        },

        freeze(id, withinMs) {
            const { pid } = runningChild(id)
            process.kill(-pid, 'SIGSTOP')
            return {
                observed: async () => {
                    const deadline = Date.now() + withinMs
                    while (processState(pid) !== 'T') {
                        if (Date.now() > deadline) {
                            return false
                        }
                        await sleep(STATE_POLL_MS)
                    }
                    return true
                },
                release: () => {
                    signal(-pid, 'SIGCONT')
                    return Promise.resolve()
                },
            }
        },

        exits: () => [...recorded],
    }
}
