import { existsSync, readFileSync, statSync } from 'node:fs'
import { resolve } from 'node:path'
import { z } from 'zod'

import type {
    ApiToolLibrary,
    ApiToolLibraryOptions,
    SkillsLibrary,
    SkillsLibraryOptions,
} from '@posthog/mcp/src/cli/library-types'

import type { WorkloadProvider } from '@/ci/providers/registry'
import { parseJson, parseJsonOrUndefined } from '@/core/json'
import type { Prompts } from '@/core/prompts'
import type { Env, Runtime, Secrets } from '@/core/runtime'

import { run } from './cli'
import { parseProviderIdToken } from './posthog/tokens'

export interface FakeRuntimeOptions {
    env?: Env
    platform?: NodeJS.Platform
    stdoutIsTTY?: boolean
    columns?: number
    cwd?: string
    files?: Record<string, string>
    stdin?: string
    // Read files from disk instead of `files`, for commands that scan real build output.
    useDisk?: boolean
    // Links from a path to the absolute path they point to, which `realPath` follows.
    links?: Record<string, string>
    // Answers to prompts, in the order hog asks them. A prompt with no answer left fails the test.
    answers?: string[]
    // Answers every API request. Without it, requests fail with HTTP 500. A string body is sent
    // as is, for JSON that JSON.stringify can't produce.
    respond?: (
        url: string,
        body: unknown,
        authorization: string | null
    ) => { status: number; body: unknown; headers?: Record<string, string> }
    telemetryToken?: string
    // The MCP tool catalog `hog api` loads, or a function that builds it from the catalog hog downloaded.
    // Without it, loading the catalog fails the test.
    apiTools?: ApiToolLibrary | ((options: ApiToolLibraryOptions) => ApiToolLibrary)
    // Builds the skills library `hog skills read` loads. Without it, loading the skills fails the test.
    skills?: (options: SkillsLibraryOptions) => SkillsLibrary
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
        // The answer lists the values picked, separated by commas.
        multiselect: async (message) => (await next(message)).split(',').filter(Boolean) as never,
        text: (message) => next(message),
        password: (message) => next(message),
        confirm: async (message) => (await next(message)) === 'yes',
        note: () => {},
        spinner: () => ({ stop: () => {}, error: () => {} }),
    }
}

// Requests carry JSON, except OAuth requests, which are form encoded.
function parseBody(body: string): unknown {
    return parseJsonOrUndefined(body, z.unknown()) ?? Object.fromEntries(new URLSearchParams(body))
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
        platform: options.platform ?? 'linux',
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
            const body = init?.body === undefined ? undefined : parseBody(String(init.body))
            requests.push({ method: init?.method ?? 'GET', url, body })
            const authorization = new Headers(init?.headers).get('authorization')
            const reply = options.respond?.(url, body, authorization) ?? {
                status: 500,
                body: { detail: 'no fake response' },
            }
            const text = typeof reply.body === 'string' ? reply.body : JSON.stringify(reply.body)
            return new Response(text, { status: reply.status, headers: reply.headers })
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
        realPath: async (path) => {
            const resolved = resolve(path)
            const link = Object.keys(options.links ?? {}).find(
                (from) => resolved === from || resolved.startsWith(`${from}/`)
            )
            return link === undefined ? resolved : `${options.links?.[link]}${resolved.slice(link.length)}`
        },
        replaceFile: async (path, contents) => {
            files[path] = contents
        },
        writePrivateFile: async (path, contents) => {
            files[path] = contents
        },
        createFile: async (path, contents) => {
            if (path in files) {
                return false
            }
            files[path] = contents
            return true
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
        loadApiTools: async (libraryOptions = {}) => {
            if (!options.apiTools) {
                throw new Error('This test loads the API tools without passing apiTools')
            }
            return typeof options.apiTools === 'function' ? options.apiTools(libraryOptions) : options.apiTools
        },
        loadSkills: async (skillsOptions) => {
            if (!options.skills) {
                throw new Error('This test loads the skills without passing skills')
            }
            return options.skills(skillsOptions)
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
    json(): unknown
    json<S extends z.ZodType>(schema: S): z.output<S>
    error(): ErrorOutput
}

const ErrorOutputSchema = z.object({
    error: z.looseObject({ code: z.string(), message: z.string(), hint: z.string().optional() }),
})

type ErrorOutput = z.output<typeof ErrorOutputSchema>['error']

const UNREADABLE_OUTPUT = { code: 'unreadable_test_output' }

export function readJson(text: string): unknown
export function readJson<S extends z.ZodType>(text: string, schema: S): z.output<S>
export function readJson(text: string, schema: z.ZodType = z.unknown()): unknown {
    return parseJson(text, schema, UNREADABLE_OUTPUT)
}

function jsonReader(text: () => string): HogRun['json'] {
    function read(): unknown
    function read<S extends z.ZodType>(schema: S): z.output<S>
    function read(schema: z.ZodType = z.unknown()): unknown {
        return readJson(text(), schema)
    }
    return read
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
        json: jsonReader(() => runtime.stdout()),
        error: () => readJson(runtime.stderr(), ErrorOutputSchema).error,
    }
}

// A CI provider for tests, so they don't depend on which real providers hog supports. A job is a
// Fake CI job when FAKE_CI is "true", and its OIDC token is FAKE_CI_TOKEN.
export const FAKE_WORKLOAD_PROVIDER: WorkloadProvider = {
    key: 'fake_ci',
    name: 'Fake CI',
    detect: (env) => env.FAKE_CI === 'true',
    fetchToken: async (runtime) =>
        runtime.env.FAKE_CI_TOKEN ? parseProviderIdToken(runtime.env.FAKE_CI_TOKEN) : undefined,
    missingTokenHint: 'Turn on OIDC tokens in Fake CI.',
    configPath: '.fake-ci.yml',
    nameFromRemote: (remote) => remote.match(/ci\.example\.com[:/](.+?)(?:\.git)?$/)?.[1],
}
