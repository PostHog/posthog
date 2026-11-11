import { ChildProcess, spawn } from 'child_process'
import { once } from 'events'
import { closeSync, openSync } from 'fs'
import path from 'path'

import { terminate } from './processes'
import { Role, RoleSpec } from './roles'

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
    exits(): RoleExit[]
}

export function createSupervisor(options: SupervisorOptions): Supervisor {
    const children = new Map<Role, ChildProcess>()
    const restarts = new Set<NodeJS.Timeout>()
    const recorded: RoleExit[] = []
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
            recorded.push({ role: spec.role, at: new Date().toISOString(), code, signal, byValve: false })
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
            const running = [...children.values()]
            children.clear()
            const exited = running
                .filter((child) => child.exitCode === null && child.signalCode === null)
                .map((child) => once(child, 'exit'))
            await terminate(
                { groups: running.flatMap((child) => (child.pid ? [child.pid] : [])), pids: [] },
                options.graceMs
            )
            await Promise.all(exited)
        },

        exits: () => [...recorded],
    }
}
