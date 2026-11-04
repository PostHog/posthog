import { existsSync, readFileSync, statSync } from 'node:fs'

import type { ApiToolLibrary } from '@posthog/mcp/src/cli/library-types'

import type { Prompts } from '@/core/prompts'
import type { Env, Runtime, Secrets } from '@/core/runtime'

import { run } from './cli'

export interface FakeRuntimeOptions {
    env?: Env
    stdoutIsTTY?: boolean
    columns?: number
    cwd?: string
    files?: Record<string, string>
    stdin?: string
    // Read files from disk instead of `files`, for commands that scan real build output.
    useDisk?: boolean
    // Answers to prompts, in the order hog asks them. A prompt with no answer left fails the test.
    answers?: string[]
    // Answers every API request. Without it, requests fail with HTTP 500. A string body is sent
    // as is, for JSON that JSON.stringify can't produce.
    respond?: (url: string, body: unknown) => { status: number; body: unknown }
    telemetryToken?: string
    // The MCP tool catalog `hog api` loads. Without it, loading the catalog fails the test.
    apiTools?: ApiToolLibrary
    // Items already in the keychain, by name.
    keychain?: Record<string, string>
    // Replaces the keychain, to fake one that is slow, unavailable or denied.
    secrets?: (runtime: FakeRuntime) => Secrets
}

export interface FakeRuntime extends Runtime {
    stdout: () => string
    stderr: () => string
    requests: { method: string; url: string; body: unknown }[]
    files: Record<string, string>
    opened: string[]
    tls: { verify: boolean }
    keychain: Record<string, string>
}

function fakePrompts(answers: string[]): Prompts {
    const next = async (message: string): Promise<string> => {
        const value = answers.shift()
        if (value === undefined) {
            throw new Error(`No answer for the prompt "${message}"`)
        }
        return value
    }
    return {
        select: (message) => next(message) as never,
        text: (message) => next(message),
        password: (message) => next(message),
        confirm: async (message) => (await next(message)) === 'yes',
        note: () => {},
        spinner: () => ({ stop: () => {}, error: () => {} }),
    }
}

function memorySecrets(items: Record<string, string>): Secrets {
    return {
        get: async (name) => items[name] ?? null,
        set: async (name, value) => {
            items[name] = value
        },
        delete: async (name) => {
            const existed = name in items
            delete items[name]
            return existed
        },
    }
}

// A clock that only moves when hog sleeps, so polling runs instantly. Timers fire in the order they
// are due, and only once no other work is left, so a race between a timeout and a slow call ends as
// it would in real time.
function fakeClock(start: number): { now: () => number; sleep: Runtime['sleep'] } {
    let clock = start
    let sequence = 0
    let scheduled = false
    const timers: { at: number; sequence: number; fire: () => void }[] = []
    const fireNext = (): void => {
        scheduled = false
        timers.sort((a, b) => a.at - b.at || a.sequence - b.sequence)
        const next = timers.shift()
        if (next) {
            clock = Math.max(clock, next.at)
            next.fire()
            schedule()
        }
    }
    const schedule = (): void => {
        if (!scheduled && timers.length > 0) {
            scheduled = true
            setImmediate(fireNext)
        }
    }
    return {
        now: () => clock,
        sleep: (ms, signal) =>
            new Promise((resolve) => {
                if (signal?.aborted) {
                    resolve()
                    return
                }
                const timer = { at: clock + ms, sequence: sequence++, fire: resolve }
                timers.push(timer)
                signal?.addEventListener(
                    'abort',
                    () => {
                        // A timer that already fired is gone, and splice(-1) would drop another one.
                        const index = timers.indexOf(timer)
                        if (index >= 0) {
                            timers.splice(index, 1)
                        }
                        resolve()
                    },
                    { once: true }
                )
                schedule()
            }),
    }
}

export function fakeRuntime(options: FakeRuntimeOptions = {}): FakeRuntime {
    let stdout = ''
    let stderr = ''
    const requests: FakeRuntime['requests'] = []
    const files = { ...options.files }
    const opened: string[] = []
    const tls = { verify: true }
    const keychain = { ...options.keychain }
    const clock = fakeClock(Date.UTC(2026, 0, 1))
    const runtime: FakeRuntime = {
        env: options.env ?? {},
        platform: 'linux',
        isDevelopment: false,
        stdinIsTTY: options.stdoutIsTTY ?? false,
        stdoutIsTTY: options.stdoutIsTTY ?? false,
        stdoutHasColors: options.stdoutIsTTY ?? false,
        stdoutColumns: options.columns,
        writeStdout: (text) => {
            stdout += text
        },
        writeStderr: (text) => {
            stderr += text
        },
        fetch: (async (input: string | URL | Request, init?: RequestInit) => {
            const url = String(input)
            const body = init?.body === undefined ? undefined : JSON.parse(String(init.body))
            requests.push({ method: init?.method ?? 'GET', url, body })
            const reply = options.respond?.(url, body) ?? { status: 500, body: { detail: 'no fake response' } }
            const text = typeof reply.body === 'string' ? reply.body : JSON.stringify(reply.body)
            return new Response(text, { status: reply.status })
        }) as typeof fetch,
        now: clock.now,
        sleep: clock.sleep,
        homeDir: () => '/home/test',
        cwd: () => options.cwd ?? '/work',
        // A path exists when it is a file, or a folder some file sits under.
        exists: async (path) =>
            options.useDisk
                ? existsSync(path)
                : path in files || Object.keys(files).some((file) => file.startsWith(`${path}/`)),
        readFile: async (path) => {
            if (options.useDisk) {
                return readFileSync(path, 'utf8')
            }
            const contents = files[path]
            if (contents === undefined) {
                throw Object.assign(new Error(`ENOENT: no such file or directory, open '${path}'`), { code: 'ENOENT' })
            }
            return contents
        },
        isDirectory: async (path) =>
            options.useDisk
                ? existsSync(path) && statSync(path).isDirectory()
                : Object.keys(files).some((file) => file.startsWith(`${path.replace(/\/$/, '')}/`)),
        listFiles: async (folder) => {
            const prefix = `${folder.replace(/\/$/, '')}/`
            return Object.keys(files)
                .filter((file) => file.startsWith(prefix) && !file.slice(prefix.length).includes('/'))
                .map((file) => file.slice(prefix.length))
                .sort()
        },
        glob: async (pattern, cwd) => {
            const prefix = `${cwd.replace(/\/$/, '')}/`
            const glob = new Bun.Glob(pattern)
            return Object.keys(files)
                .filter((file) => file.startsWith(prefix) && glob.match(file.slice(prefix.length)))
                .map((file) => file.slice(prefix.length))
                .sort()
        },
        writeFile: async (path, contents) => {
            files[path] = contents
        },
        writePrivateFile: async (path, contents) => {
            files[path] = contents
        },
        removeFile: async (path) => {
            delete files[path]
        },
        readStdin: async () => options.stdin ?? '',
        openUrl: async (url) => {
            opened.push(url)
            return true
        },
        prompts: fakePrompts([...(options.answers ?? [])]),
        secrets: memorySecrets(keychain),
        telemetryToken: options.telemetryToken,
        skipTlsVerification: () => {
            tls.verify = false
        },
        loadApiTools: async () => {
            if (!options.apiTools) {
                throw new Error('This test loads the API tools without passing apiTools')
            }
            return options.apiTools
        },
        stdout: () => stdout,
        stderr: () => stderr,
        requests,
        files,
        opened,
        tls,
        keychain,
    }
    if (options.secrets) {
        runtime.secrets = options.secrets(runtime)
    }
    return runtime
}

// Credentials that pass validation, plus NO_COLOR so text output has no escape codes.
export const TEST_CREDENTIALS = {
    HOG_PERSONAL_API_KEY: 'phx_test',
    HOG_PROJECT_ID: '7',
    HOG_HOST: 'https://ph.example.com',
    NO_COLOR: '1',
}

export interface HogRun {
    exitCode: number
    stdout: string
    stderr: string
    requests: FakeRuntime['requests']
    files: Record<string, string>
    opened: string[]
    elapsedMs: number
    tls: { verify: boolean }
    keychain: Record<string, string>
    json: () => any
    error: () => any
}

export async function runHog(argv: string[], options: FakeRuntimeOptions = {}): Promise<HogRun> {
    const runtime = fakeRuntime(options)
    const start = runtime.now()
    const exitCode = await run(argv, runtime)
    return {
        exitCode,
        stdout: runtime.stdout(),
        stderr: runtime.stderr(),
        requests: runtime.requests,
        files: runtime.files,
        opened: runtime.opened,
        elapsedMs: runtime.now() - start,
        tls: runtime.tls,
        keychain: runtime.keychain,
        json: () => JSON.parse(runtime.stdout()),
        error: () => JSON.parse(runtime.stderr()).error,
    }
}
