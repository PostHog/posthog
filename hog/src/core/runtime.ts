import { randomUUID } from 'node:crypto'
import { access, chmod, lstat, mkdir, readdir, readFile, realpath, rename, rm, stat, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { basename, dirname, join, resolve } from 'node:path'

import type { ApiToolLibrary, SkillsLibrary, SkillsLibraryOptions } from '@posthog/mcp/src/cli/library-types'

import { BUILD_DATE, VERSION } from '@/version'

import { HogError } from './errors'
import { clackPrompts, type Prompts } from './prompts'
import { DEFAULT_TELEMETRY_TOKEN } from './telemetry'

export type Env = Readonly<Record<string, string | undefined>>

// `timeoutMs` starts when the request leaves, so time spent waiting for --rate-limit doesn't count.
// `skipRateLimit` marks a signed storage URL, which posthog-cli's --rate-limit doesn't count either.
export type RuntimeFetch = (
    input: string | URL | Request,
    init?: RequestInit & { timeoutMs?: number; skipRateLimit?: boolean }
) => Promise<Response>

// The operating system's secret store: Keychain on macOS, Credential Manager on Windows and Secret
// Service on Linux. Every item belongs to hog's own service, so `name` only has to be unique within hog.
export interface Secrets {
    // Resolves to null when there is no item with this name.
    get: (name: string) => Promise<string | null>
    set: (name: string, value: string) => Promise<void>
    // Resolves to false when there was no item to delete.
    delete: (name: string) => Promise<boolean>
}

// Everything a command touches outside its own arguments. Tests build one by hand,
// so no command reads `process` or the network directly.
export interface Runtime {
    env: Env
    platform: NodeJS.Platform
    arch: string
    // True for `bun src/index.ts`, false for a compiled hog. A run from source keeps its credentials
    // and settings apart, so it never reads or replaces those of an installed hog.
    isDevelopment: boolean
    // A local build has no date, and never checks for updates.
    build: { version: string; date: string | undefined }
    execPath: string
    isMusl: () => Promise<boolean>
    runCommand: (argv: string[]) => Promise<number>
    // Windows can't replace a running exe, so it renames the old one to hog.old.exe, which the next run deletes.
    replaceExecutable: (path: string, contents: Uint8Array) => Promise<void>
    stdinIsTTY: boolean
    stdoutIsTTY: boolean
    stdoutHasColors: boolean
    stdoutColumns: number | undefined
    writeStdout: (text: string) => void
    writeStderr: (text: string) => void
    fetch: RuntimeFetch
    now: () => number
    // Resolves early when `signal` aborts, so a timer that lost a race doesn't keep hog running.
    sleep: (ms: number, signal?: AbortSignal) => Promise<void>
    homeDir: () => string | undefined
    cwd: () => string
    exists: (path: string) => Promise<boolean>
    readFile: (path: string) => Promise<string>
    isDirectory: (path: string) => Promise<boolean>
    // The names of the files directly in a folder, sorted. Folders inside it are left out.
    listFiles: (folder: string) => Promise<string[]>
    // The files under `cwd` that match a glob pattern, as paths relative to it, sorted.
    glob: (pattern: string, cwd: string) => Promise<string[]>
    // Writes a project file, such as a generated SDK, and creates the folders above it.
    writeFile: (path: string, contents: string) => Promise<void>
    // Where a write to `path` lands, with every link resolved. A missing file resolves inside its
    // folder's real path. Throws for a link to a missing file, whose write could land anywhere.
    realPath: (path: string) => Promise<string>
    // Both replace the file with one rename, so a failed write leaves the old contents. `replaceFile`
    // keeps an existing file's mode, and `writePrivateFile` makes the file readable only by its owner.
    replaceFile: (path: string, contents: string) => Promise<void>
    writePrivateFile: (path: string, contents: string) => Promise<void>
    // Creates a private file unless the path exists, and resolves to false if it does, so it works as a lock.
    createFile: (path: string, contents: string) => Promise<boolean>
    removeFile: (path: string) => Promise<void>
    readStdin: () => Promise<string>
    // Resolves to false when no browser could be started, for example on a server without one.
    openUrl: (url: string) => Promise<boolean>
    prompts: Prompts
    secrets: Secrets
    // The project token for anonymous usage events. Undefined turns them off, as in tests.
    telemetryToken: string | undefined
    // Accepts any TLS certificate from here on, for every request, including the API tools' own.
    skipTlsVerification: () => void
    // The MCP server's tool catalog, which `hog api` browses and calls. Loaded on first use: it is large.
    loadApiTools: () => Promise<ApiToolLibrary>
    // The PostHog agent skills `hog skills read` serves. Loaded on first use, like the tool catalog.
    loadSkills: (options: SkillsLibraryOptions) => Promise<SkillsLibrary>
}

const BROWSER_LAUNCH_MS = 1000

// `pnpm --filter @posthog/mcp build:cli:library` writes both libraries, so a run from source before it fails with a hint.
async function loadMcpLibrary<T>(load: () => Promise<T>, code: string, name: string): Promise<T> {
    try {
        return await load()
    } catch (error) {
        if ((error as { code?: string }).code === 'ERR_MODULE_NOT_FOUND') {
            throw new HogError(
                code,
                `hog couldn't find ${name}.`,
                'Run `pnpm --filter @posthog/hog build:mcp`, then run the command again.'
            )
        }
        throw error
    }
}

function browserCommand(url: string): string[] {
    switch (process.platform) {
        case 'darwin':
            return ['open', url]
        case 'win32':
            // Not `cmd /c start`: cmd treats the `&` in a URL's query string as a command separator.
            return ['rundll32', 'url.dll,FileProtocolHandler', url]
        default:
            return ['xdg-open', url]
    }
}

// `bun src/index.ts` runs as the bun executable, a compiled hog as itself.
const FROM_SOURCE = basename(process.execPath).replace(/\.exe$/i, '') === 'bun'

// Keychain calls that haven't settled. A call hog stopped waiting for, such as one behind a dialog
// nobody answers, keeps the process alive, so the entry point ends the process when this is not zero.
let pendingSecretCalls = 0

export function hasPendingSecretCalls(): boolean {
    return pendingSecretCalls > 0
}

async function tracked<T>(call: () => Promise<T>): Promise<T> {
    pendingSecretCalls += 1
    try {
        return await call()
    } finally {
        pendingSecretCalls -= 1
    }
}

function bunSecrets(service: string): Secrets {
    return {
        get: (name) => tracked(() => Bun.secrets.get({ service, name })),
        // Windows only: the default `enterprise` lets a roaming profile copy the item to every machine the
        // person signs in to. Bun before 1.4.3 ignores the option, so the item still roams there.
        // TODO: require Bun 1.4.3+ (engines.bun and the flox pin) once hog can move to it.
        set: (name, value) =>
            tracked(() =>
                Bun.secrets.set({ service, name, value, persist: 'local' } as Parameters<typeof Bun.secrets.set>[0])
            ),
        delete: (name) => tracked(() => Bun.secrets.delete({ service, name })),
    }
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
    return new Promise((resolve) => {
        if (signal?.aborted) {
            resolve()
            return
        }
        const timer = setTimeout(resolve, ms)
        signal?.addEventListener(
            'abort',
            () => {
                clearTimeout(timer)
                resolve()
            },
            { once: true }
        )
    })
}

// A rename is atomic, so a crash never leaves a half-written file. The temporary name is random and
// `wx` refuses an existing path, so nobody can plant a symlink there first. `keep` keeps an existing
// file's mode, and a new file gets the default one. The mode is set with chmod, because the umask
// would strip bits from a mode passed to the write.
async function writeAtomically(path: string, contents: string, mode: number | 'keep'): Promise<void> {
    const fileMode =
        mode === 'keep'
            ? await stat(path).then(
                  (stats) => stats.mode & 0o7777,
                  () => undefined
              )
            : mode
    const temporary = `${path}.${randomUUID()}.tmp`

    try {
        await writeFile(temporary, contents, { flag: 'wx', mode: fileMode === undefined ? 0o666 : 0o600 })
        if (fileMode !== undefined) {
            await chmod(temporary, fileMode)
        }

        await rename(temporary, path)
    } catch (error) {
        await rm(temporary, { force: true })
        throw error
    }
}

async function realPath(path: string): Promise<string> {
    try {
        return await realpath(path)
    } catch (error) {
        const missing = (error as NodeJS.ErrnoException).code === 'ENOENT'
        if (
            !missing ||
            (await lstat(path).then(
                () => true,
                () => false
            ))
        ) {
            throw error
        }
        return join(await realpath(dirname(path)), basename(path))
    }
}

async function replaceExecutable(path: string, contents: Uint8Array): Promise<void> {
    const temporary = join(dirname(path), `.hog.${randomUUID()}.tmp`)
    const old = join(dirname(path), 'hog.old.exe')
    let movedAside = false
    try {
        await writeFile(temporary, contents, { flag: 'wx', mode: 0o755 })
        await chmod(temporary, 0o755)
        if (process.platform === 'win32') {
            await rm(old, { force: true })
            await rename(path, old)
            movedAside = true
        }
        await rename(temporary, path)
    } catch (error) {
        await rm(temporary, { force: true })
        if (movedAside) {
            await rename(old, path).catch(() => {})
        }
        throw error
    }
}

async function isMusl(): Promise<boolean> {
    for (const folder of ['/lib', '/usr/lib']) {
        const names = await readdir(folder).catch(() => [] as string[])
        if (names.some((name) => name.startsWith('ld-musl-'))) {
            return true
        }
    }
    return false
}

export function processRuntime(): Runtime {
    return {
        env: process.env,
        platform: process.platform,
        arch: process.arch,
        isDevelopment: FROM_SOURCE,
        build: { version: VERSION, date: BUILD_DATE },
        execPath: process.execPath,
        isMusl: () => (process.platform === 'linux' ? isMusl() : Promise.resolve(false)),
        runCommand: async (argv) => {
            // Not the caller's folder: pnpm reads a project's .pnpmfile.cjs even for a global install.
            const child = Bun.spawn(argv, { cwd: homedir(), stdin: 'inherit', stdout: 'inherit', stderr: 'inherit' })
            return child.exited
        },
        replaceExecutable,
        stdinIsTTY: process.stdin.isTTY === true,
        stdoutIsTTY: process.stdout.isTTY === true,
        stdoutHasColors: process.stdout.isTTY === true && process.stdout.hasColors(),
        stdoutColumns: process.stdout.columns || undefined,
        writeStdout: (text) => {
            process.stdout.write(text)
        },
        writeStderr: (text) => {
            process.stderr.write(text)
        },
        fetch: (input, { timeoutMs, skipRateLimit: _skipRateLimit, ...init } = {}) =>
            globalThis.fetch(
                input,
                timeoutMs === undefined ? init : { ...init, signal: AbortSignal.timeout(timeoutMs) }
            ),
        now: () => Date.now(),
        sleep,
        homeDir: () => {
            try {
                const home = homedir()
                // When HOME is unset and the user has no passwd entry, Node throws but Bun returns "/".
                // A "/" that came from HOME itself is a real choice, so it still counts.
                return !home || (home === '/' && !process.env.HOME) ? undefined : home
            } catch {
                return undefined
            }
        },
        cwd: () => process.cwd(),
        exists: (path) =>
            access(path).then(
                () => true,
                () => false
            ),
        readFile: (path) => readFile(path, 'utf8'),
        isDirectory: (path) =>
            stat(path).then(
                (stats) => stats.isDirectory(),
                () => false
            ),
        listFiles: async (folder) => {
            const entries = await readdir(folder, { withFileTypes: true })
            return entries
                .filter((entry) => entry.isFile())
                .map((entry) => entry.name)
                .sort()
        },
        glob: async (pattern, cwd) =>
            (await Array.fromAsync(new Bun.Glob(pattern).scan({ cwd, onlyFiles: true }))).sort(),
        writeFile: async (path, contents) => {
            await mkdir(dirname(path), { recursive: true })
            await writeFile(path, contents)
        },
        realPath: (path) => realPath(resolve(path)),
        replaceFile: (path, contents) => writeAtomically(path, contents, 'keep'),
        writePrivateFile: async (path, contents) => {
            await mkdir(dirname(path), { recursive: true, mode: 0o700 })
            await writeAtomically(path, contents, 0o600)
        },
        createFile: async (path, contents) => {
            await mkdir(dirname(path), { recursive: true, mode: 0o700 })
            try {
                await writeFile(path, contents, { mode: 0o600, flag: 'wx' })
                return true
            } catch (error) {
                if ((error as NodeJS.ErrnoException).code === 'EEXIST') {
                    return false
                }
                throw error
            }
        },
        removeFile: (path) => rm(path, { force: true }),
        readStdin: () => new Response(Bun.stdin.stream()).text(),
        openUrl: async (url) => {
            if (!URL.canParse(url) || !['http:', 'https:'].includes(new URL(url).protocol)) {
                return false
            }
            try {
                const child = Bun.spawn(browserCommand(url), { stdin: 'ignore', stdout: 'ignore', stderr: 'ignore' })
                child.unref()
                // Some openers, like xdg-open, stay attached to the browser they start. Waiting for
                // them to exit would hold up polling, so hog only waits long enough to see a failed launch.
                const code = await Promise.race([child.exited, Bun.sleep(BROWSER_LAUNCH_MS).then(() => undefined)])
                return code === undefined || code === 0
            } catch {
                return false
            }
        },
        prompts: clackPrompts(),
        secrets: bunSecrets(FROM_SOURCE ? 'com.posthog.hog.dev' : 'com.posthog.hog'),
        telemetryToken: DEFAULT_TELEMETRY_TOKEN,
        skipTlsVerification: () => {
            // Runs only for --skip-ssl-verification, posthog-cli's opt-in flag for self-hosted certificates.
            process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0' // nosemgrep: trailofbits.generic.node-disable-certificate-validation.node-disable-certificate-validation
        },
        loadApiTools: () =>
            loadMcpLibrary(
                async () => (await import('@posthog/mcp/dist/cli-library.mjs')).createApiToolLibrary(),
                'api_tools_missing',
                'the API tool catalog'
            ),
        loadSkills: (options) =>
            loadMcpLibrary(
                async () => (await import('@posthog/mcp/dist/cli-skills.mjs')).createSkillsLibrary(options),
                'skills_missing',
                'the skills library'
            ),
    }
}
