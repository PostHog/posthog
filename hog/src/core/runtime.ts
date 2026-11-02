import { randomUUID } from 'node:crypto'
import { access, mkdir, readdir, readFile, rename, rm, stat, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname } from 'node:path'

import type { ApiToolLibrary } from '@posthog/mcp/src/cli/library-types'

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

// Everything a command touches outside its own arguments. Tests build one by hand,
// so no command reads `process` or the network directly.
export interface Runtime {
    env: Env
    stdinIsTTY: boolean
    stdoutIsTTY: boolean
    stdoutHasColors: boolean
    stdoutColumns: number | undefined
    writeStdout: (text: string) => void
    writeStderr: (text: string) => void
    fetch: RuntimeFetch
    now: () => number
    sleep: (ms: number) => Promise<void>
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
    writePrivateFile: (path: string, contents: string) => Promise<void>
    removeFile: (path: string) => Promise<void>
    readStdin: () => Promise<string>
    // Resolves to false when no browser could be started, for example on a server without one.
    openUrl: (url: string) => Promise<boolean>
    prompts: Prompts
    // The project token for anonymous usage events. Undefined turns them off, as in tests.
    telemetryToken: string | undefined
    // Accepts any TLS certificate from here on, for every request, including the API tools' own.
    skipTlsVerification: () => void
    // The MCP server's tool catalog, which `hog api` browses and calls. Loaded on first use: it is large.
    loadApiTools: () => Promise<ApiToolLibrary>
}

const BROWSER_LAUNCH_MS = 1000

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

export function processRuntime(): Runtime {
    return {
        env: process.env,
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
        sleep: (ms) => Bun.sleep(ms),
        homeDir: () => {
            try {
                return homedir()
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
        // A rename is atomic, so a crash never leaves a half-written file. The temporary name is
        // random and `wx` refuses an existing path, so nobody can plant a symlink there first.
        writePrivateFile: async (path, contents) => {
            await mkdir(dirname(path), { recursive: true, mode: 0o700 })
            const temporary = `${path}.${randomUUID()}.tmp`
            try {
                await writeFile(temporary, contents, { mode: 0o600, flag: 'wx' })
                await rename(temporary, path)
            } catch (error) {
                await rm(temporary, { force: true })
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
        telemetryToken: DEFAULT_TELEMETRY_TOKEN,
        skipTlsVerification: () => {
            // Runs only for --skip-ssl-verification, posthog-cli's opt-in flag for self-hosted certificates.
            process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0' // nosemgrep: trailofbits.generic.node-disable-certificate-validation.node-disable-certificate-validation
        },
        loadApiTools: async () => {
            try {
                const { createApiToolLibrary } = await import('@posthog/mcp/dist/cli-library.mjs')
                return createApiToolLibrary()
            } catch (error) {
                if ((error as { code?: string }).code === 'ERR_MODULE_NOT_FOUND') {
                    throw new HogError(
                        'api_tools_missing',
                        "hog couldn't find the API tool catalog.",
                        'Run `pnpm --filter @posthog/hog build:mcp`, then run the command again.'
                    )
                }
                throw error
            }
        },
    }
}
