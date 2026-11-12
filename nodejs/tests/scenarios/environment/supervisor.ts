import { ChildProcess, spawn } from 'child_process'
import { once } from 'events'
import { closeSync, openSync } from 'fs'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'

import { terminate } from './processes'
import { Role, RoleSpec } from './roles'

const EXIT_REPORTED_WITHIN_MS = 2000

const isRunning = (child: ChildProcess): boolean => child.exitCode === null && child.signalCode === null

export type RoleExit = {
    role: Role
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
    kill(role: Role, withinMs: number): Promise<boolean>
    exits(): RoleExit[]
}

export function createSupervisor(options: SupervisorOptions): Supervisor {
    const children = new Map<Role, ChildProcess>()
    const restarts = new Set<NodeJS.Timeout>()
    const recorded: RoleExit[] = []
    const killedByValve = new WeakSet<ChildProcess>()
    let stopping = false

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
        const log = openSync(path.join(options.logDir, `${spec.role}.log`), 'a')
        const child = spawn(options.command, options.args, {
            cwd: options.cwd,
            env: spec.env,
            detached: true,
            stdio: ['ignore', log, log],
        })
        closeSync(log)
        children.set(spec.role, child)
        child.once('error', (error) => {
            if (children.get(spec.role) === child) {
                children.delete(spec.role)
            }
            if (stopping || child.pid !== undefined) {
                return
            }
            recorded.push({
                role: spec.role,
                at: new Date().toISOString(),
                code: null,
                signal: null,
                byValve: false,
                error: error.message,
            })
            relaunchLater(spec)
        })
        child.once('exit', (code, signal) => {
            if (children.get(spec.role) === child) {
                children.delete(spec.role)
            }
            if (stopping) {
                return
            }
            void terminate({ groups: child.pid ? [child.pid] : [], pids: [] }, 0)
            recorded.push({
                role: spec.role,
                at: new Date().toISOString(),
                code,
                signal,
                byValve: killedByValve.has(child),
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

        async kill(role, withinMs) {
            const child = children.get(role)
            if (child?.pid === undefined || child.exitCode !== null || child.signalCode !== null) {
                throw new Error(`${role} is not running`)
            }
            killedByValve.add(child)
            const exited = once(child, 'exit').then(() => true)
            process.kill(-child.pid, 'SIGKILL')
            const gaveUp = new AbortController()
            const outcome = await Promise.race([
                exited,
                sleep(withinMs, false, { signal: gaveUp.signal }).catch(() => false),
            ])
            gaveUp.abort()
            return outcome
        },

        exits: () => [...recorded],
    }
}
