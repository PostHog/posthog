import { chmod, mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises'
import { homedir } from 'node:os'
import { dirname } from 'node:path'

import { clackPrompts, type Prompts } from './prompts'

export type Env = Readonly<Record<string, string | undefined>>

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
    fetch: typeof fetch
    now: () => number
    sleep: (ms: number) => Promise<void>
    homeDir: () => string | undefined
    readFile: (path: string) => Promise<string>
    writePrivateFile: (path: string, contents: string) => Promise<void>
    removeFile: (path: string) => Promise<void>
    readStdin: () => Promise<string>
    // Resolves to false when no browser could be started, for example on a server without one.
    openUrl: (url: string) => Promise<boolean>
    prompts: Prompts
}

function browserCommand(url: string): string[] {
    switch (process.platform) {
        case 'darwin':
            return ['open', url]
        case 'win32':
            // The empty string is the window title `start` expects before the URL.
            return ['cmd', '/c', 'start', '""', url]
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
        fetch: globalThis.fetch,
        now: () => Date.now(),
        sleep: (ms) => Bun.sleep(ms),
        homeDir: () => {
            try {
                return homedir()
            } catch {
                return undefined
            }
        },
        readFile: (path) => readFile(path, 'utf8'),
        // A rename is atomic, so a crash never leaves a half-written file, and the mode is set
        // before the contents land.
        writePrivateFile: async (path, contents) => {
            await mkdir(dirname(path), { recursive: true, mode: 0o700 })
            const temporary = `${path}.${process.pid}.tmp`
            await writeFile(temporary, contents, { mode: 0o600 })
            await chmod(temporary, 0o600)
            await rename(temporary, path)
        },
        removeFile: (path) => rm(path, { force: true }),
        readStdin: () => new Response(Bun.stdin.stream()).text(),
        openUrl: async (url) => {
            try {
                const child = Bun.spawn(browserCommand(url), { stdin: 'ignore', stdout: 'ignore', stderr: 'ignore' })
                return (await child.exited) === 0
            } catch {
                return false
            }
        },
        prompts: clackPrompts(),
    }
}
