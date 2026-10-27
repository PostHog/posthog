import type { Env, Runtime } from './runtime'

export interface FakeRuntime extends Runtime {
    stdout: () => string
    stderr: () => string
    requests: { url: string; body: unknown }[]
}

export function fakeRuntime(options: {
    env?: Env
    stdoutIsTTY?: boolean
    files?: Record<string, string>
    stdin?: string
    respond?: (url: string, body: unknown) => { status: number; body: unknown }
}): FakeRuntime {
    let stdout = ''
    let stderr = ''
    const requests: { url: string; body: unknown }[] = []
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
            const body = JSON.parse(String(init?.body ?? 'null'))
            requests.push({ url, body })
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
