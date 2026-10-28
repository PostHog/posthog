import { mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, relative } from 'node:path'

import { run } from '@/cli'
import { processRuntime } from '@/core/runtime'

import { startFakeServer } from './fake-server'
import { write } from './fixtures'
import { normalize, type NormalizedRequest } from './normalize'
import type { ParityScenario } from './scenarios'

export interface ParityResult {
    exitCode: number
    requests: NormalizedRequest[]
    // Every file in the folder after the run, for scenarios that rewrite files.
    files?: Record<string, string>
}

function environment(serverUrl: string, home: string): Record<string, string> {
    return {
        HOME: home,
        POSTHOG_HOME: home,
        POSTHOG_CLI_API_KEY: 'phx_parity',
        POSTHOG_CLI_PROJECT_ID: '1',
        POSTHOG_CLI_HOST: serverUrl,
        NO_COLOR: '1',
    }
}

const strictUtf8 = new TextDecoder('utf-8', { fatal: true })

// Text files stay readable in the golden, so a diff shows what changed. Other bytes are base64.
export function encodeFile(bytes: Uint8Array): string {
    try {
        return `utf8:${strictUtf8.decode(bytes)}`
    } catch {
        return `base64:${Buffer.from(bytes).toString('base64')}`
    }
}

export function decodeFile(text: string): Uint8Array {
    return text.startsWith('utf8:') ? Buffer.from(text.slice(5), 'utf8') : Buffer.from(text.slice(7), 'base64')
}

function snapshot(folder: string): Record<string, string> {
    const files: Record<string, string> = {}
    const visit = (path: string): void => {
        for (const entry of readdirSync(path, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : 1))) {
            const full = join(path, entry.name)
            if (entry.isDirectory() && entry.name !== '.git') {
                visit(full)
            } else if (entry.isFile()) {
                files[relative(folder, full)] = encodeFile(readFileSync(full))
            }
        }
    }
    visit(folder)
    return files
}

async function invoke(
    args: string[],
    cli: { rust: string } | 'hog',
    folder: string,
    env: Record<string, string>
): Promise<number> {
    if (cli === 'hog') {
        const runtime = {
            ...processRuntime(),
            env,
            cwd: () => folder,
            stdinIsTTY: false,
            stdoutIsTTY: false,
            stdoutHasColors: false,
            writeStdout: () => {},
            writeStderr: () => {},
            // Retry delays don't change what is sent, so tests skip them.
            sleep: async () => {},
        }
        return run(args, runtime)
    }
    const child = Bun.spawn([cli.rust, ...args], {
        cwd: folder,
        env: { PATH: process.env.PATH ?? '', ...env },
        stdout: 'pipe',
        stderr: 'pipe',
    })
    return child.exited
}

export async function runScenario(scenario: ParityScenario, cli: { rust: string } | 'hog'): Promise<ParityResult> {
    const folder = mkdtempSync(join(tmpdir(), 'hog-parity-'))
    const home = mkdtempSync(join(tmpdir(), 'hog-parity-home-'))
    write(folder, scenario.files())
    scenario.setup?.()
    const server = startFakeServer(scenario.server)
    try {
        const env = environment(server.url, home)
        for (const step of scenario.before ?? []) {
            await invoke(cli === 'hog' ? step.hog : step.rust, cli, folder, env)
        }
        let exitCode = 0
        for (let index = 0; index < (scenario.runs ?? 1); index++) {
            server.requests.length = 0
            exitCode = await invoke(cli === 'hog' ? scenario.hog : scenario.rust, cli, folder, env)
        }
        return {
            exitCode,
            requests: normalize(server.requests),
            ...(scenario.snapshot ? { files: snapshot(folder) } : {}),
        }
    } finally {
        server.stop()
        rmSync(folder, { recursive: true, force: true })
        rmSync(home, { recursive: true, force: true })
    }
}

const UUID_V7 = /[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/g

// Symbol-set mode mints random UUIDv7 chunk ids. They become <v7-n>, numbered by first appearance in
// path order, so two runs compare equal when they put the same kind of id in the same places.
export function withoutRandomIds(result: ParityResult): ParityResult {
    const names = new Map<string, string>()
    const rename = (text: string): string =>
        text.replace(UUID_V7, (id) => {
            if (!names.has(id)) {
                names.set(id, `<v7-${names.size + 1}>`)
            }
            return names.get(id)!
        })
    return {
        ...result,
        files:
            result.files &&
            Object.fromEntries(Object.entries(result.files).map(([path, text]) => [path, rename(text)])),
    }
}
