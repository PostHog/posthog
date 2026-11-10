import { readFileSync, readdirSync } from 'fs'
import { setTimeout as sleep } from 'timers/promises'

export const MARKER = 'SCENARIO_RUNNER=1'

const CDP_NODE_ENTRY = /posthog-node|src\/index\.ts/

export type ProcEntry = { pid: number; pgid: number; cmdline: string; environ: string[] | null }

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

export function planCleanup(entries: ProcEntry[], selfPid: number): CleanupPlan {
    const selfPgid = entries.find((entry) => entry.pid === selfPid)?.pgid
    const others = entries.filter((entry) => entry.pid !== selfPid)
    const leftovers = others.filter(isMarked)
    const sharedWithUnmarked = (pgid: number): boolean =>
        pgid === selfPgid || others.some((entry) => entry.pgid === pgid && !isMarked(entry))
    return {
        groups: [...new Set(leftovers.map((entry) => entry.pgid).filter((pgid) => !sharedWithUnmarked(pgid)))],
        pids: leftovers.filter((entry) => sharedWithUnmarked(entry.pgid)).map((entry) => entry.pid),
        strangers: others.filter((entry) => !isMarked(entry) && CDP_NODE_ENTRY.test(entry.cmdline)),
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

function readEntry(root: string, name: string): ProcEntry | null {
    const stat = readOptional(`${root}/${name}/stat`)
    const cmdline = readOptional(`${root}/${name}/cmdline`)
    if (stat === null || cmdline === null) {
        return null
    }
    return {
        pid: Number(name),
        pgid: Number(stat.slice(stat.lastIndexOf(')') + 2).split(' ')[2]),
        cmdline: cmdline.split('\0').join(' ').trim(),
        environ: readOptional(`${root}/${name}/environ`)?.split('\0') ?? null,
    }
}

export function readProcs(root = '/proc'): ProcEntry[] {
    return readdirSync(root)
        .filter((name) => /^\d+$/.test(name))
        .flatMap((name) => readEntry(root, name) ?? [])
}

function signal(target: number, sig: NodeJS.Signals | 0): boolean {
    try {
        process.kill(target, sig)
        return true
    } catch {
        return false
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
