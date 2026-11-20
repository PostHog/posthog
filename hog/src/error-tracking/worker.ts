import { realpathSync } from 'node:fs'
import { basename, dirname, join } from 'node:path'
import { z } from 'zod'

import { HogError } from '@/core/errors'
import { parseJson, parseJsonOrUndefined } from '@/core/json'
import { parseOrThrow, type Schema } from '@/core/schema'

// hog-worker is the Rust program in hog/worker/ that reads, rewrites and writes build output with
// the code posthog-cli runs, so the bytes match. hog/worker/src/main.rs describes the requests.

// Must equal PROTOCOL in hog/worker/src/main.rs. hog and the worker are two files, so an upgrade
// that replaced only one of them is caught here instead of in a request the other can't read.
export const WORKER_PROTOCOL = 1

const WORKER_NAME = 'hog-worker'
const WINDOWS_SUFFIX = '.exe'
// Where `pnpm --filter hog build:worker` puts the worker, for a hog that runs from source.
const SOURCE_BUILD = join(import.meta.dir, '..', '..', 'worker', 'target', 'release')

const isBun = (execPath: string): boolean => basename(execPath).replace(/\.exe$/i, '') === 'bun'

// The worker sits next to the hog binary, and hog never looks anywhere else: a `hog-worker` found
// through PATH could be any program. A symlinked hog, as Homebrew installs it, resolves first.
export function workerPath(execPath: string = process.execPath, platform: NodeJS.Platform = process.platform): string {
    const name = platform === 'win32' ? `${WORKER_NAME}${WINDOWS_SUFFIX}` : WORKER_NAME
    if (isBun(execPath)) {
        return join(SOURCE_BUILD, name)
    }

    let resolved = execPath
    try {
        resolved = realpathSync(execPath)
    } catch {}
    return join(dirname(resolved), name)
}

const Hello = z.object({ type: z.literal('hello'), protocol: z.number(), version: z.string() })

const Answer = z.union([
    z.object({ ok: z.literal(true), result: z.unknown() }),
    z.object({ ok: z.literal(false), error: z.object({ code: z.string(), message: z.string() }) }),
])

const PairState = z.object({
    id: z.number(),
    sourcePath: z.string(),
    mapPath: z.string(),
    mapRealPath: z.string(),
    chunkId: z.string().nullable(),
    sourceDebugId: z.string().nullable(),
    mapChunkId: z.string().nullable(),
    mapReleaseId: z.string().nullable(),
    mapDebugId: z.string().nullable(),
})
export type PairState = z.output<typeof PairState>

const Detected = z.object({ sourcemap: z.array(z.number()), composed: z.array(z.number()) })
const Pairs = z.object({
    pairs: z.array(z.union([PairState, z.object({ skipped: z.string() }), z.null()])),
})
const InjectAction = z.enum(['injected', 'release_updated', 'unchanged'])
const Outcomes = z.object({
    outcomes: z.array(
        z.object({ action: InjectAction, chunkId: z.string(), warnings: z.array(z.string()), pair: PairState })
    ),
})
const Done = z.object({})

export type InjectOutcome = z.output<typeof Outcomes>['outcomes'][number]
export type PairAnswer = z.output<typeof Pairs>['pairs'][number]

export interface DetectCandidate {
    path: string
    bundle: boolean
    map: boolean
}

async function* readLines(stream: ReadableStream<Uint8Array>): AsyncGenerator<string> {
    const decoder = new TextDecoder()
    let buffered = ''
    for await (const chunk of stream) {
        buffered += decoder.decode(chunk, { stream: true })

        let newline = buffered.indexOf('\n')
        while (newline >= 0) {
            yield buffered.slice(0, newline)
            buffered = buffered.slice(newline + 1)
            newline = buffered.indexOf('\n')
        }
    }
    if (buffered) {
        yield buffered
    }
}

interface Running {
    child: Bun.Subprocess<'pipe', 'pipe', 'inherit'>
    lines: AsyncGenerator<string>
}

export class Worker {
    private running: Promise<Running> | undefined

    constructor(private readonly path: string = workerPath()) {}

    // Started by the first request, so a command that fails on its arguments never starts one.
    private start(): Promise<Running> {
        this.running ??= (async () => {
            let child: Running['child']
            try {
                child = Bun.spawn([this.path], { stdin: 'pipe', stdout: 'pipe', stderr: 'inherit' })
            } catch (error) {
                throw new HogError(
                    'worker_missing',
                    `hog couldn't start hog-worker at ${this.path}: ${(error as Error).message}`,
                    isBun(process.execPath)
                        ? 'Run `pnpm --filter hog build:worker` to build it.'
                        : 'hog-worker ships next to hog. Install hog again to get both.'
                )
            }
            const lines = readLines(child.stdout)

            const first = await lines.next()
            const hello = first.done ? undefined : parseJsonOrUndefined(first.value, Hello)
            if (hello?.protocol !== WORKER_PROTOCOL) {
                child.kill()
                throw new HogError(
                    'worker_mismatch',
                    hello
                        ? `hog-worker ${hello.version} at ${this.path} speaks protocol ${hello.protocol}, and this hog needs protocol ${WORKER_PROTOCOL}.`
                        : `The program at ${this.path} didn't answer like hog-worker.`,
                    'hog and hog-worker must come from the same release. Install hog again to replace both.'
                )
            }
            return { child, lines }
        })()
        return this.running
    }

    private async call<T>(request: Record<string, unknown>, result: Schema<T>): Promise<T> {
        const { child, lines } = await this.start()
        child.stdin.write(`${JSON.stringify(request)}\n`)
        child.stdin.flush()

        const line = await lines.next()
        if (line.done) {
            throw new HogError(
                'worker_failed',
                `hog-worker stopped without an answer (exit code ${await child.exited}).`
            )
        }
        const failure = { code: 'worker_failed', context: 'hog-worker sent' }
        const message = parseJson(line.value, Answer, failure)
        if (!message.ok) {
            // Every failure other than a bug in hog is a file the worker could not read or write.
            if (message.error.code === 'bad_request') {
                throw new HogError('worker_failed', `hog-worker refused a request: ${message.error.message}`)
            }
            throw new Error(message.error.message)
        }
        return parseOrThrow(result, message.result, failure)
    }

    async detect(
        files: DetectCandidate[],
        publicPathPrefix: string | undefined
    ): Promise<{ sourcemap: Set<string>; composed: Set<string> }> {
        const asked = files.filter((file) => file.bundle || file.map)
        if (asked.length === 0) {
            return { sourcemap: new Set(), composed: new Set() }
        }
        const found = await this.call(
            { op: 'detect', files: asked, publicPathPrefix: publicPathPrefix ?? null },
            Detected
        )
        const paths = (indices: number[]): Set<string> => new Set(indices.map((index) => asked[index]!.path))
        return { sourcemap: paths(found.sourcemap), composed: paths(found.composed) }
    }

    async readPairs(paths: string[], publicPathPrefix: string | undefined): Promise<PairAnswer[]> {
        if (paths.length === 0) {
            return []
        }
        return (await this.call({ op: 'read_pairs', paths, publicPathPrefix: publicPathPrefix ?? null }, Pairs)).pairs
    }

    async drop(ids: number[]): Promise<void> {
        if (ids.length > 0) {
            await this.call({ op: 'drop', ids }, Done)
        }
    }

    async inject(
        ids: number[],
        mode: 'event' | 'symbol-set',
        releaseId: string | null,
        newChunkIds: string[] = []
    ): Promise<InjectOutcome[]> {
        if (ids.length === 0) {
            return []
        }
        return (await this.call({ op: 'inject', ids, mode, releaseId, newChunkIds }, Outcomes)).outcomes
    }

    async save(ids: number[]): Promise<void> {
        if (ids.length > 0) {
            await this.call({ op: 'save', ids }, Done)
        }
    }

    async close(): Promise<void> {
        const running = await this.running?.catch(() => undefined)
        if (running) {
            running.child.stdin.end()
            await running.child.exited
        }
    }
}

export async function withWorker<T>(work: (worker: Worker) => Promise<T>): Promise<T> {
    const worker = new Worker()
    try {
        return await work(worker)
    } finally {
        await worker.close()
    }
}
