import { createHash } from 'crypto'
import { readFileSync, readdirSync } from 'fs'
import net from 'net'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'

export const MARKER_KEY = 'SCENARIO_RUNNER'

const PROC_ROOT = '/proc'
const HOLDER_READ_TIMEOUT_MS = 2000
const KILL_SETTLES_MS = 2000

export type ProcEntry = { pid: number; pgid: number; cmdline: string; environ: string[] | null }

export type Targets = { groups: number[]; pids: number[] }

export type CleanupPlan = Targets & { strangers: ProcEntry[] }

export class StackConflictError extends Error {
    readonly exitCode = 2

    constructor(message: string) {
        super(message)
        this.name = 'StackConflictError'
    }
}

const isMarked = (entry: ProcEntry): boolean =>
    entry.environ?.some((variable) => variable.startsWith(`${MARKER_KEY}=`)) ?? false

export function planCleanup(entries: ProcEntry[], selfPid: number, stateDir: string): CleanupPlan {
    const selfPgid = entries.find((entry) => entry.pid === selfPid)?.pgid
    const others = entries.filter((entry) => entry.pid !== selfPid)
    const ours = (entry: ProcEntry): boolean => entry.environ?.includes(`${MARKER_KEY}=${stateDir}`) ?? false
    const leftovers = others.filter(ours)
    const sharedWithOthers = (pgid: number): boolean =>
        pgid === selfPgid || others.some((entry) => entry.pgid === pgid && !ours(entry))
    return {
        groups: [...new Set(leftovers.map((entry) => entry.pgid).filter((pgid) => !sharedWithOthers(pgid)))],
        pids: leftovers.filter((entry) => sharedWithOthers(entry.pgid)).map((entry) => entry.pid),
        strangers: others.filter((entry) => !ours(entry) && isMarked(entry)),
    }
}

const runnerOf = (entry: ProcEntry): string | undefined =>
    entry.environ?.find((variable) => variable.startsWith(`${MARKER_KEY}=`))?.slice(MARKER_KEY.length + 1)

const listed = (entries: ProcEntry[]): string => entries.map((entry) => `${entry.pid} (${entry.cmdline})`).join(', ')

export async function strangerConflict(strangers: ProcEntry[]): Promise<StackConflictError> {
    const runners = [...new Set(strangers.flatMap((entry) => runnerOf(entry) ?? []))]
    const held = (
        await Promise.all(
            runners.map(async (runner) => {
                const holder = await runnerHolding(lockAddress(runner))
                return holder ? [{ runner, holder }] : []
            })
        )
    ).flat()
    const sentences = held.map(({ runner, holder }) => {
        const roles = strangers.filter((entry) => runnerOf(entry) === runner)
        return `Roles of scenario runner ${holder.pid}, which uses ${runner}, are running: ${listed(roles)}. That runner restarts roles that are killed, so run \`${stopCommand(holder, roles)}\``
    })
    const killable = strangers.filter((entry) => !held.some(({ runner }) => runner === runnerOf(entry)))
    if (killable.length > 0) {
        sentences.push(
            `CDP processes the scenario runner did not start are running: ${listed(killable)}. Run \`kill ${killable.map((entry) => entry.pid).join(' ')}\``
        )
    }
    return new StackConflictError(`${sentences.join('. ')}, then run the scenario again.`)
}

function readOptional(file: string): string | null {
    try {
        return readFileSync(file, 'utf8')
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
        environ: readOptional(path.join(dir, 'environ'))?.split('\0') ?? null,
    }
}

export function processState(pid: number): string | null {
    const stat = readOptional(path.join(PROC_ROOT, String(pid), 'stat'))
    return stat === null ? null : stat.slice(stat.lastIndexOf(')') + 2, stat.lastIndexOf(')') + 3)
}

export function readProcs(): ProcEntry[] {
    return readdirSync(PROC_ROOT)
        .filter((name) => /^\d+$/.test(name))
        .flatMap((name) => readEntry(name) ?? [])
}

export function signal(target: number, sig: NodeJS.Signals | 0): boolean {
    try {
        process.kill(target, sig)
        return true
    } catch {
        return false
    }
}

function holderOf(address: string): Promise<string> {
    return new Promise((resolve) => {
        let said = ''
        const socket = net.connect(address)
        socket.setTimeout(HOLDER_READ_TIMEOUT_MS, () => socket.destroy())
        socket.on('data', (chunk) => (said += chunk))
        socket.once('error', () => undefined)
        socket.once('close', () => resolve(said.trim()))
    })
}

type Holder = { pid: string }

async function runnerHolding(address: string): Promise<Holder | undefined> {
    const answer = await holderOf(address)
    return /^\d+$/.test(answer) ? { pid: answer } : undefined
}

const stopCommand = (holder: Holder, roles: ProcEntry[] = []): string =>
    ['kill', holder.pid, ...roles.map((entry) => entry.pid)].join(' ')

export const lockAddress = (stateDir: string): string =>
    `\0posthog-scenarios-${createHash('sha256').update(stateDir).digest('hex').slice(0, 16)}`

export async function holdRunLock(stateDir: string, retried = false): Promise<() => Promise<void>> {
    const address = lockAddress(stateDir)
    const server = net.createServer((socket) => {
        socket.on('error', () => undefined)
        socket.end(String(process.pid))
    })
    try {
        await new Promise<void>((resolve, reject) => {
            server.once('error', reject)
            server.listen(address, resolve)
        })
    } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'EADDRINUSE') {
            throw error
        }
        const holder = await runnerHolding(address)
        if (holder) {
            throw new StackConflictError(
                `Scenario runner ${holder.pid} is already running from ${stateDir}. Run \`${stopCommand(holder)}\`, then run the scenario again.`
            )
        }
        if (retried) {
            throw new StackConflictError(
                `Another scenario runner holds ${stateDir} and does not answer. Find what holds it with \`ss -xlp | grep posthog-scenarios\`, stop it, then run the scenario again.`
            )
        }
        return holdRunLock(stateDir, true)
    }
    server.unref()
    return () => new Promise((resolve) => server.close(() => resolve()))
}

const targetsOf = ({ groups, pids }: Targets): number[] => [...groups.map((pgid) => -pgid), ...pids]

export async function terminate(targets: Targets, graceMs: number): Promise<void> {
    let alive = targetsOf(targets).filter((target) => signal(target, 'SIGCONT') && signal(target, 'SIGTERM'))
    const deadline = Date.now() + graceMs
    while (alive.length > 0 && Date.now() < deadline) {
        await sleep(100)
        alive = alive.filter((target) => signal(target, 0))
    }
    alive.forEach((target) => signal(target, 'SIGKILL'))
    const killedBy = Date.now() + KILL_SETTLES_MS
    while (alive.length > 0 && Date.now() < killedBy) {
        await sleep(20)
        alive = alive.filter((target) => signal(target, 0))
    }
}
