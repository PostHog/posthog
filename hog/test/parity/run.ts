import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { run } from '@/cli'
import { processRuntime } from '@/core/runtime'

import { startFakeServer } from './fake-server'
import { write } from './fixtures'
import { normalize, type NormalizedRequest } from './normalize'
import type { ParityScenario } from './scenarios'

export interface ParityResult {
    exitCode: number
    requests: NormalizedRequest[]
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

export async function runScenario(scenario: ParityScenario, cli: { rust: string } | 'hog'): Promise<ParityResult> {
    const folder = mkdtempSync(join(tmpdir(), 'hog-parity-'))
    const home = mkdtempSync(join(tmpdir(), 'hog-parity-home-'))
    write(folder, scenario.files)
    const server = startFakeServer(scenario.server)
    try {
        let exitCode = 0
        for (let index = 0; index < (scenario.runs ?? 1); index++) {
            server.requests.length = 0
            const env = environment(server.url, home)
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
                exitCode = await run(scenario.hog, runtime)
            } else {
                const child = Bun.spawn([cli.rust, ...scenario.rust], {
                    cwd: folder,
                    env: { PATH: process.env.PATH ?? '', ...env },
                    stdout: 'pipe',
                    stderr: 'pipe',
                })
                exitCode = await child.exited
            }
        }
        return { exitCode, requests: normalize(server.requests) }
    } finally {
        server.stop()
        rmSync(folder, { recursive: true, force: true })
        rmSync(home, { recursive: true, force: true })
    }
}
