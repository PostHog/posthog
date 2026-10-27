import type { Env, Runtime } from '@/core/runtime'

import { run } from './cli'

export interface FakeRuntimeOptions {
    env?: Env
    stdoutIsTTY?: boolean
    files?: Record<string, string>
    stdin?: string
    // Answers every API request. Without it, requests fail with HTTP 500.
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
            return new Response(JSON.stringify(reply.body), { status: reply.status })
        }) as typeof fetch,
        homeDir: () => '/home/test',
        readFile: async (path) => {
            const contents = files[path]
            if (contents === undefined) {
                throw new Error(`ENOENT: ${path}`)
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
