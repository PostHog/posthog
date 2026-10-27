import { readFile } from 'node:fs/promises'
import { homedir } from 'node:os'

export type Env = Readonly<Record<string, string | undefined>>

// Everything a command touches outside its own arguments. Tests build one by hand,
// so no command reads `process` or the network directly.
export interface Runtime {
    env: Env
    stdoutIsTTY: boolean
    writeStdout: (text: string) => void
    writeStderr: (text: string) => void
    fetch: typeof fetch
    homeDir: () => string | undefined
    readFile: (path: string) => Promise<string>
    readStdin: () => Promise<string>
}

export function processRuntime(): Runtime {
    return {
        env: process.env,
        stdoutIsTTY: process.stdout.isTTY === true,
        writeStdout: (text) => {
            process.stdout.write(text)
        },
        writeStderr: (text) => {
            process.stderr.write(text)
        },
        fetch: globalThis.fetch,
        homeDir: () => {
            try {
                return homedir()
            } catch {
                return undefined
            }
        },
        readFile: (path) => readFile(path, 'utf8'),
        readStdin: () => new Response(Bun.stdin.stream()).text(),
    }
}
