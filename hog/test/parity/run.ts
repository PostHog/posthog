import { createHash } from 'node:crypto'
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
    // The files the run created or changed, and null for the ones it deleted.
    files?: Record<string, string | null>
}

// posthog-cli reads the POSTHOG_CLI_ names and hog the HOG_ ones, so both CLIs get the same credentials.
function environment(serverUrl: string, home: string): Record<string, string> {
    return {
        HOME: home,
        POSTHOG_HOME: home,
        HOG_HOME: home,
        POSTHOG_CLI_API_KEY: 'phx_parity',
        POSTHOG_CLI_PROJECT_ID: '1',
        POSTHOG_CLI_HOST: serverUrl,
        HOG_API_KEY: 'phx_parity',
        HOG_PROJECT_ID: '1',
        HOG_HOST: serverUrl,
        NO_COLOR: '1',
    }
}

const strictUtf8 = new TextDecoder('utf-8', { fatal: true })

// Files over this size are compared by hash, so goldens stay small. Smaller text files stay
// readable, so a golden diff shows what changed.
const INLINE_LIMIT = 2048

export function encodeFile(bytes: Uint8Array): string {
    try {
        return `utf8:${strictUtf8.decode(bytes)}`
    } catch {
        return `base64:${Buffer.from(bytes).toString('base64')}`
    }
}

export function decodeFile(text: string): Uint8Array {
    if (text.startsWith('sha512:')) {
        throw new Error('This golden stores the file as a hash. Record the scenario with `fullSnapshot`.')
    }
    return text.startsWith('utf8:') ? Buffer.from(text.slice(5), 'utf8') : Buffer.from(text.slice(7), 'base64')
}

// Only what differs from the inputs, so goldens don't repeat fixture files the run left alone.
// Random chunk ids become placeholders before a large file is hashed, so the hash still compares
// where the ids go. `full` keeps every file whole and unchanged, for scenarios others start from.
function changedFiles(
    folder: string,
    inputs: Record<string, string | Uint8Array>,
    options: { full: boolean; randomIds: boolean }
): Record<string, string | null> {
    const before: Record<string, string> = {}
    for (const [path, contents] of Object.entries(inputs)) {
        before[path] = encodeFile(typeof contents === 'string' ? Buffer.from(contents) : contents)
    }
    const after = snapshot(folder)
    let changed: Record<string, string | null> = {}
    for (const path of [...new Set([...Object.keys(before), ...Object.keys(after)])].sort()) {
        if (before[path] !== after[path]) {
            changed[path] = after[path] ?? null
        }
    }
    if (options.full) {
        return changed
    }
    if (options.randomIds) {
        changed = withoutRandomIds({ exitCode: 0, requests: [], files: changed }).files!
    }
    return Object.fromEntries(
        Object.entries(changed).map(([path, text]) => [
            path,
            text === null || text.length <= INLINE_LIMIT
                ? text
                : `sha512:${createHash('sha512').update(text).digest('hex')}`,
        ])
    )
}

function snapshot(folder: string): Record<string, string> {
    const files: Record<string, string> = {}
    const visit = (path: string): void => {
        for (const entry of readdirSync(path, { withFileTypes: true }).sort((a, b) => (a.name < b.name ? -1 : 1))) {
            const entryPath = join(path, entry.name)
            if (entry.isDirectory() && entry.name !== '.git') {
                visit(entryPath)
            } else if (entry.isFile()) {
                files[relative(folder, entryPath)] = encodeFile(readFileSync(entryPath))
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
    const inputs = scenario.files()
    write(folder, inputs)
    scenario.setup?.()
    const server = startFakeServer(scenario.server)
    server.store(scenario.objects?.() ?? [])
    try {
        const env = { ...environment(server.url, home), ...scenario.env }
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
            ...(scenario.snapshot
                ? {
                      files: changedFiles(folder, inputs, {
                          full: scenario.fullSnapshot === true,
                          randomIds: scenario.randomIds === true,
                      }),
                  }
                : {}),
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
            Object.fromEntries(
                Object.entries(result.files).map(([path, text]) => [path, text === null ? null : rename(text)])
            ),
    }
}
