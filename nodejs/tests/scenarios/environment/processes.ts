import { createHash } from 'crypto'
import { readFileSync, readdirSync, readlinkSync, realpathSync } from 'fs'
import net from 'net'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'

import { getPluginServerCapabilities } from '~/capabilities'
import { stringToPluginServerMode } from '~/common/config'

export const MARKER = 'SCENARIO_RUNNER=1'

const PROC_ROOT = '/proc'
const HOLDER_READ_TIMEOUT_MS = 2000

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

const ENTRY_POINTS = ['bin/posthog-node', 'src/index.ts', 'dist/index.js']

const entryPointsOf = (nodejsDir: string): string[] => [
    path.join(path.dirname(nodejsDir), 'bin', 'posthog-node'),
    ...ENTRY_POINTS.map((entryPoint) => path.join(nodejsDir, entryPoint)),
]

function launchesNode(entry: ProcEntry, nodejsDir: string): boolean {
    const args = entry.cmdline.split(' ')
    const cwd = entry.cwd
    if (cwd === null) {
        return args.some((arg) =>
            ENTRY_POINTS.some((entryPoint) => arg === entryPoint || arg.endsWith(`/${entryPoint}`))
        )
    }
    const entryPoints = entryPointsOf(nodejsDir)
    return args.some((arg) => entryPoints.includes(path.resolve(cwd, arg)))
}

function servesCdp(environ: string[]): boolean {
    const read = (name: string): string | undefined =>
        environ.find((variable) => variable.startsWith(`${name}=`))?.slice(name.length + 1)
    const mode = read('PLUGIN_SERVER_MODE')
    try {
        const capabilities = getPluginServerCapabilities({
            PLUGIN_SERVER_MODE: mode ? (stringToPluginServerMode[mode] ?? null) : null,
            NODEJS_CAPABILITY_GROUPS: read('NODEJS_CAPABILITY_GROUPS') ?? '',
        })
        return Object.entries(capabilities ?? {}).some(([name, enabled]) => name.startsWith('cdp') && enabled)
    } catch {
        return false
    }
}

function runsCdp(entry: ProcEntry, nodejsDir: string): boolean {
    return launchesNode(entry, nodejsDir) && (entry.environ === null || servesCdp(entry.environ))
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

export async function holdRunLock(stateDir: string): Promise<() => Promise<void>> {
    const address = `\0posthog-scenarios-${createHash('sha256').update(realpathSync(stateDir)).digest('hex').slice(0, 16)}`
    const server = net.createServer((socket) => socket.end(String(process.pid)))
    try {
        await new Promise<void>((resolve, reject) => {
            server.once('error', reject)
            server.listen(address, resolve)
        })
    } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'EADDRINUSE') {
            throw error
        }
        const holder = (await holderOf(address)) || 'another process'
        throw new StackConflictError(`Scenario runner ${holder} is already running from ${stateDir}.`, `kill ${holder}`)
    }
    server.unref()
    return () => new Promise((resolve) => server.close(() => resolve()))
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
