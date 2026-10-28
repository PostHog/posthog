import type { Env, Runtime } from '@/core/runtime'

import { run } from './cli'

export interface FakeRuntimeOptions {
    env?: Env
    stdoutIsTTY?: boolean
    columns?: number
    files?: Record<string, string>
    stdin?: string
    // Answers every API request. Without it, requests fail with HTTP 500. A string body is sent
    // as is, for JSON that JSON.stringify can't produce.
    respond?: (url: string, body: unknown) => { status: number; body: unknown }
}

export interface FakeRuntime extends Runtime {
    stdout: () => string
    stderr: () => string
    requests: { method: string; url: string; body: unknown }[]
}

export function fakeRuntime(options: FakeRuntimeOptions = {}): FakeRuntime {
    let stdout = ''
    let stderr = ''
    const requests: FakeRuntime['requests'] = []
    const files = options.files ?? {}
    return {
        env: options.env ?? {},
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
        homeDir: () => '/home/test',
        readFile: async (path) => {
            const contents = files[path]
            if (contents === undefined) {
                throw Object.assign(new Error(`ENOENT: no such file or directory, open '${path}'`), { code: 'ENOENT' })
            }
            return contents
        },
        readStdin: async () => options.stdin ?? '',
        stdout: () => stdout,
        stderr: () => stderr,
        requests,
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
        json: () => JSON.parse(runtime.stdout()),
        error: () => JSON.parse(runtime.stderr()).error,
    }
}
