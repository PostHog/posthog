import { existsSync, readFileSync } from 'node:fs'

import type { Prompts } from '@/core/prompts'
import type { Env, Runtime } from '@/core/runtime'

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
}

export interface FakeRuntime extends Runtime {
    stdout: () => string
    stderr: () => string
    requests: { method: string; url: string; body: unknown }[]
    files: Record<string, string>
    opened: string[]
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
        note: () => {},
        spinner: () => ({ stop: () => {}, error: () => {} }),
    }
}

export function fakeRuntime(options: FakeRuntimeOptions = {}): FakeRuntime {
    let stdout = ''
    let stderr = ''
    const requests: FakeRuntime['requests'] = []
    const files = { ...options.files }
    const opened: string[] = []
    // A clock that only moves when hog sleeps, so polling runs instantly.
    let clock = Date.UTC(2026, 0, 1)
    return {
        env: options.env ?? {},
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
        now: () => clock,
        sleep: async (ms) => {
            clock += ms
        },
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
        stdout: () => stdout,
        stderr: () => stderr,
        requests,
        files,
        opened,
    }
}

// Credentials that pass validation, plus NO_COLOR so text output has no escape codes.
export const TEST_CREDENTIALS = {
    POSTHOG_CLI_API_KEY: 'phx_test',
    POSTHOG_CLI_PROJECT_ID: '7',
    POSTHOG_CLI_HOST: 'https://ph.example.com',
    NO_COLOR: '1',
}

export interface HogRun {
    exitCode: number
    stdout: string
    stderr: string
    requests: FakeRuntime['requests']
    files: Record<string, string>
    opened: string[]
    json: () => any
    error: () => any
}

export async function runHog(argv: string[], options: FakeRuntimeOptions = {}): Promise<HogRun> {
    const runtime = fakeRuntime(options)
    const exitCode = await run(argv, runtime)
    return {
        exitCode,
        stdout: runtime.stdout(),
        stderr: runtime.stderr(),
        requests: runtime.requests,
        files: runtime.files,
        opened: runtime.opened,
        json: () => JSON.parse(runtime.stdout()),
        error: () => JSON.parse(runtime.stderr()).error,
    }
}
