import { createHash } from 'crypto'
import { readFileSync, readdirSync, readlinkSync } from 'fs'
import net from 'net'
import path from 'path'
import { setTimeout as sleep } from 'timers/promises'

import { getPluginServerCapabilities } from '~/capabilities'
import { stringToPluginServerMode } from '~/common/config'

export const MARKER_KEY = 'SCENARIO_RUNNER'

const PROC_ROOT = '/proc'
const HOLDER_READ_TIMEOUT_MS = 2000
const KILL_SETTLES_MS = 2000
const LISTENING = '00010000'

export type ProcEntry = { pid: number; pgid: number; cmdline: string; cwd: string | null; environ: string[] | null }

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

const ENTRY_POINTS = ['bin/posthog-node', 'src/index.ts', 'dist/index.js']
const NODE_LAUNCHERS = ['node', 'tsx']
const SHELLS = ['sh', 'bash', 'dash', 'zsh']
const INLINE_CODE = /^(-e|-p|-pe|--eval|--print)(=|$)/
const SCRIPT_FILE = /\.[cm]?[jt]sx?$/

const entryPointsOf = (nodejsDir: string): string[] => [
    path.join(path.dirname(nodejsDir), 'bin', 'posthog-node'),
    ...ENTRY_POINTS.map((entryPoint) => path.join(nodejsDir, entryPoint)),
]

const isTsx = (arg: string): boolean =>
    path.basename(arg) === 'tsx' || arg.endsWith(path.join('tsx', 'dist', 'cli.mjs'))

const isOptionValue = (previous: string | undefined): boolean =>
    previous !== undefined && previous.startsWith('-') && !previous.includes('=')

const isForeignScript = (arg: string, previous: string | undefined): boolean =>
    !arg.startsWith('-') &&
    !isTsx(arg) &&
    !isOptionValue(previous) &&
    (SCRIPT_FILE.test(arg) || arg.split('/').includes('bin'))

function launchesNode(entry: ProcEntry, nodejsDir: string): boolean {
    const args = entry.cmdline.split(' ')
    const entryPoints = entryPointsOf(nodejsDir)
    const isEntryPoint = (arg: string): boolean =>
        entryPoints.includes(entry.cwd === null ? arg : path.resolve(entry.cwd, arg))
    const [program = '', ...rest] = SHELLS.includes(path.basename(args[0])) ? args.slice(1) : args
    if (isEntryPoint(program)) {
        return true
    }
    const at = rest.findIndex(isEntryPoint)
    const before = rest.slice(0, at)
    return (
        NODE_LAUNCHERS.includes(path.basename(program)) &&
        at !== -1 &&
        !before.some((arg) => INLINE_CODE.test(arg)) &&
        !before.some((arg, index) => isForeignScript(arg, rest[index - 1]))
    )
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

export function planCleanup(entries: ProcEntry[], selfPid: number, nodejsDir: string, stateDir: string): CleanupPlan {
    const selfPgid = entries.find((entry) => entry.pid === selfPid)?.pgid
    const others = entries.filter((entry) => entry.pid !== selfPid)
    const ours = (entry: ProcEntry): boolean => entry.environ?.includes(`${MARKER_KEY}=${stateDir}`) ?? false
    const leftovers = others.filter(ours)
    const sharedWithOthers = (pgid: number): boolean =>
        pgid === selfPgid || others.some((entry) => entry.pgid === pgid && !ours(entry))
    return {
        groups: [...new Set(leftovers.map((entry) => entry.pgid).filter((pgid) => !sharedWithOthers(pgid)))],
        pids: leftovers.filter((entry) => sharedWithOthers(entry.pgid)).map((entry) => entry.pid),
        strangers: others.filter((entry) => !ours(entry) && (isMarked(entry) || runsCdp(entry, nodejsDir))),
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
        const silence = holder.answered ? '' : ' but does not answer with a pid and may be suspended'
        return `Roles of scenario runner ${holder.pid}, which uses ${runner}${silence}, are running: ${listed(roles)}. That runner restarts roles that are killed, so run \`${stopCommand(holder, roles)}\``
    })
    const killable = strangers.filter((entry) => !held.some(({ runner }) => runner === runnerOf(entry)))
    if (killable.length > 0) {
        sentences.push(
            `CDP processes the scenario runner did not start are running: ${listed(killable)}. Use \`hogli down\` if hogli started them. Run \`kill ${killable.map((entry) => entry.pid).join(' ')}\``
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

function listenerOf(address: string): string | undefined {
    const path = `@${address.slice(1)}`
    const inode = readFileSync(`${PROC_ROOT}/net/unix`, 'utf8')
        .split('\n')
        .map((line) => line.trim().split(/\s+/))
        .find((fields) => fields[7] === path && fields[3] === LISTENING)?.[6]
    const socket = `socket:[${inode}]`
    return inode === undefined
        ? undefined
        : readdirSync(PROC_ROOT)
              .filter((name) => /^\d+$/.test(name))
              .find((pid) => {
                  try {
                      return readdirSync(`${PROC_ROOT}/${pid}/fd`).some(
                          (fd) => readlinkSync(`${PROC_ROOT}/${pid}/fd/${fd}`) === socket
                      )
                  } catch {
                      return false
                  }
              })
}

type Holder = { pid: string; answered: boolean }

async function runnerHolding(address: string): Promise<Holder | undefined> {
    const answer = await holderOf(address)
    if (/^\d+$/.test(answer)) {
        return { pid: answer, answered: true }
    }
    const silent = listenerOf(address)
    return silent ? { pid: silent, answered: false } : undefined
}

const stopCommand = (holder: Holder, roles: ProcEntry[] = []): string => {
    const kill = ['kill', holder.pid, ...roles.map((entry) => entry.pid)].join(' ')
    return holder.answered ? kill : `kill -CONT ${holder.pid}; ${kill}`
}

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
            const state = holder.answered
                ? `is already running from ${stateDir}`
                : `holds ${stateDir} but does not answer with a pid; it may be a suspended scenario runner (resume it with fg)`
            throw new StackConflictError(
                `${holder.answered ? 'Scenario runner' : 'Process'} ${holder.pid} ${state}. Run \`${stopCommand(holder)}\`, then run the scenario again.`
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
