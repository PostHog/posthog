import { readFileSync, readdirSync, readlinkSync, rmSync, writeFileSync } from 'fs'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'

import { CdpRole } from '../cards'

export const MARKER = 'SCENARIO_RUNNER=1'

const PROC_ROOT = '/proc'
const LOCK_FILE = 'runner.lock'

export type ProcEntry = { pid: number; pgid: number; cmdline: string; cwd: string | null; environ: string[] | null }

export type Targets = { groups: number[]; pids: number[] }

export type CleanupPlan = Targets & { strangers: ProcEntry[] }

export class StackConflictError extends Error {
    readonly exitCode = 2

    constructor(
        message: string,
        readonly stopCommand: string
    ) {
        super(`${message} Stop it with \`${stopCommand}\`, then run the scenario again.`)
        this.name = 'StackConflictError'
    }
}

const isMarked = (entry: ProcEntry): boolean => entry.environ?.includes(MARKER) ?? false

const entryPointsOf = (nodejsDir: string): string[] => [
    path.join(path.dirname(nodejsDir), 'bin', 'posthog-node'),
    path.join(nodejsDir, 'src', 'index.ts'),
    path.join(nodejsDir, 'dist', 'index.js'),
]

const CDP_MODES: string[] = ['', ...CdpRole.options]

function runsCdp(entry: ProcEntry, nodejsDir: string): boolean {
    if (entry.cwd === null) {
        return false
    }
    const entryPoints = entryPointsOf(nodejsDir)
    const cwd = entry.cwd
    const launchesNode = entry.cmdline.split(' ').some((arg) => entryPoints.includes(path.resolve(cwd, arg)))
    if (!launchesNode) {
        return false
    }
    if (entry.environ === null) {
        return true
    }
    const mode = entry.environ.find((variable) => variable.startsWith('PLUGIN_SERVER_MODE='))
    return CDP_MODES.includes(mode?.slice('PLUGIN_SERVER_MODE='.length) ?? '')
}

export function planCleanup(entries: ProcEntry[], selfPid: number, nodejsDir: string): CleanupPlan {
    const selfPgid = entries.find((entry) => entry.pid === selfPid)?.pgid
    const others = entries.filter((entry) => entry.pid !== selfPid)
    const leftovers = others.filter(isMarked)
    const sharedWithUnmarked = (pgid: number): boolean =>
        pgid === selfPgid || others.some((entry) => entry.pgid === pgid && !isMarked(entry))
    return {
        groups: [...new Set(leftovers.map((entry) => entry.pgid).filter((pgid) => !sharedWithUnmarked(pgid)))],
        pids: leftovers.filter((entry) => sharedWithUnmarked(entry.pgid)).map((entry) => entry.pid),
        strangers: others.filter((entry) => !isMarked(entry) && runsCdp(entry, nodejsDir)),
    }
}

export function strangerConflict(strangers: ProcEntry[]): StackConflictError {
    const listed = strangers.map((entry) => `${entry.pid} (${entry.cmdline})`).join(', ')
    return new StackConflictError(
        `CDP processes the scenario runner did not start are running: ${listed}. Use \`hogli down\` if hogli started them.`,
        `kill ${strangers.map((entry) => entry.pid).join(' ')}`
    )
}

function readOptional(file: string): string | null {
    try {
        return readFileSync(file, 'utf8')
    } catch {
        return null
    }
}

function linkOptional(file: string): string | null {
    try {
        return readlinkSync(file)
    } catch {
        return null
    }
}

function readEntry(name: string): ProcEntry | null {
    const dir = path.join(PROC_ROOT, name)
    const stat = readOptional(path.join(dir, 'stat'))
    const cmdline = readOptional(path.join(dir, 'cmdline'))
    if (stat === null || cmdline === null) {
        return null
    }
    return {
        pid: Number(name),
        pgid: Number(stat.slice(stat.lastIndexOf(')') + 2).split(' ')[2]),
        cmdline: cmdline.split('\0').join(' ').trim(),
        cwd: linkOptional(path.join(dir, 'cwd')),
        environ: readOptional(path.join(dir, 'environ'))?.split('\0') ?? null,
    }
}

export function readProcs(): ProcEntry[] {
    return readdirSync(PROC_ROOT)
        .filter((name) => /^\d+$/.test(name))
        .flatMap((name) => readEntry(name) ?? [])
}

function signal(target: number, sig: NodeJS.Signals | 0): boolean {
    try {
        process.kill(target, sig)
        return true
    } catch {
        return false
    }
}

function isAlive(pid: number): boolean {
    try {
        process.kill(pid, 0)
        return true
    } catch (error) {
        return (error as NodeJS.ErrnoException).code === 'EPERM'
    }
}

export function holdRunLock(stateDir: string): () => void {
    const file = path.join(stateDir, LOCK_FILE)
    const own = String(process.pid)
    const release = (): void => {
        if (readOptional(file) === own) {
            rmSync(file, { force: true })
        }
    }
    for (;;) {
        try {
            writeFileSync(file, own, { flag: 'wx' })
            return release
        } catch (error) {
            if ((error as NodeJS.ErrnoException).code !== 'EEXIST') {
                throw error
            }
        }
        const holder = Number(readOptional(file))
        if (holder === process.pid) {
            return release
        }
        if (holder > 0 && isAlive(holder)) {
            throw new StackConflictError(
                `Scenario runner ${holder} is already running from ${stateDir}.`,
                `kill ${holder}`
            )
        }
        rmSync(file, { force: true })
    }
}

const targetsOf = ({ groups, pids }: Targets): number[] => [...groups.map((pgid) => -pgid), ...pids]

export async function terminate(targets: Targets, graceMs: number): Promise<void> {
    let alive = targetsOf(targets).filter((target) => signal(target, 'SIGTERM'))
    const deadline = Date.now() + graceMs
    while (alive.length > 0 && Date.now() < deadline) {
        await sleep(100)
        alive = alive.filter((target) => signal(target, 0))
    }
    alive.forEach((target) => signal(target, 'SIGKILL'))
}
