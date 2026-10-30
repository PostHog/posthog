import { randomUUID } from 'node:crypto'
import { access, mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises'
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
    cwd: () => string
    exists: (path: string) => Promise<boolean>
    readFile: (path: string) => Promise<string>
    writePrivateFile: (path: string, contents: string) => Promise<void>
    removeFile: (path: string) => Promise<void>
    readStdin: () => Promise<string>
    // Resolves to false when no browser could be started, for example on a server without one.
    openUrl: (url: string) => Promise<boolean>
    prompts: Prompts
}

const BROWSER_LAUNCH_MS = 1000

function browserCommand(url: string): string[] {
    switch (process.platform) {
        case 'darwin':
            return ['open', url]
        case 'win32':
            // Not `cmd /c start`: cmd treats the `&` in a URL's query string as a command separator.
            return ['rundll32', 'url.dll,FileProtocolHandler', url]
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
        cwd: () => process.cwd(),
        exists: (path) =>
            access(path).then(
                () => true,
                () => false
            ),
        readFile: (path) => readFile(path, 'utf8'),
        // A rename is atomic, so a crash never leaves a half-written file. The temporary name is
        // random and `wx` refuses an existing path, so nobody can plant a symlink there first.
        writePrivateFile: async (path, contents) => {
            await mkdir(dirname(path), { recursive: true, mode: 0o700 })
            const temporary = `${path}.${randomUUID()}.tmp`
            try {
                await writeFile(temporary, contents, { mode: 0o600, flag: 'wx' })
                await rename(temporary, path)
            } catch (error) {
                await rm(temporary, { force: true })
                throw error
            }
        },
        removeFile: (path) => rm(path, { force: true }),
        readStdin: () => new Response(Bun.stdin.stream()).text(),
        openUrl: async (url) => {
            if (!URL.canParse(url) || !['http:', 'https:'].includes(new URL(url).protocol)) {
                return false
            }
            try {
                const child = Bun.spawn(browserCommand(url), { stdin: 'ignore', stdout: 'ignore', stderr: 'ignore' })
                child.unref()
                // Some openers, like xdg-open, stay attached to the browser they start. Waiting for
                // them to exit would hold up polling, so hog only waits long enough to see a failed launch.
                const code = await Promise.race([child.exited, Bun.sleep(BROWSER_LAUNCH_MS).then(() => undefined)])
                return code === undefined || code === 0
            } catch {
                return false
            }
        },
        prompts: clackPrompts(),
    }
}
