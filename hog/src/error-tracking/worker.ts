import { join, posix, win32 } from 'node:path'
import { z } from 'zod'

import type { Context } from '@/core/context'
import { HogError } from '@/core/errors'
import { parseJson, parseJsonOrUndefined } from '@/core/json'
import { canonical } from '@/core/paths'
import { FROM_SOURCE, type Runtime } from '@/core/runtime'
import { parseOrThrow, type Schema } from '@/core/schema'
import { classifyPath, type InstallMethod, upgradeAdvice, upgradeCommand } from '@/updates/install-method'
import { workerName } from '@/updates/targets'
import { BUILD_DATE, VERSION } from '@/version'

import type { ReleaseMode } from './session'

// hog-worker is the Rust program in hog/worker/ that reads, rewrites and writes build output with
// the code posthog-cli runs, so the bytes match. hog/worker/src/main.rs describes the requests.

// Must equal PROTOCOL in hog/worker/src/main.rs. hog and the worker are two files, so an upgrade
// that replaced only one of them is caught here instead of in a request the other can't read.
export const WORKER_PROTOCOL = 1

// Where `pnpm --filter hog build:worker` puts the worker, for a hog that runs from source.
const SOURCE_BUILD = join(import.meta.dir, '..', '..', 'worker', 'target', 'release')

// The worker sits next to the hog binary, and hog never looks anywhere else: a `hog-worker` found
// through PATH could be any program. A symlinked hog, as Homebrew installs it, resolves first.
export function workerPath(runtime: Pick<Runtime, 'isDevelopment' | 'execPath' | 'platform'>): string {
    const name = workerName(runtime.platform)
    if (runtime.isDevelopment) {
        return join(SOURCE_BUILD, name)
    }
    const path = runtime.platform === 'win32' ? win32 : posix
    return path.join(path.dirname(canonical(runtime.execPath)), name)
}

function upgradeHint(path: string): string {
    const method: InstallMethod = { kind: 'standalone', ...classifyPath(path), path }
    const command = upgradeCommand(method)
    return command ? `Run \`${command}\`.` : upgradeAdvice(method, '<command>')
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

const Detected = z.object({
    sourcemap: z.array(z.number()),
    composed: z.array(z.number()),
    mapping: z.array(z.number()),
    elf: z.array(z.number()),
    macho: z.array(z.number()),
})
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
const Targets = z.object({ targets: z.array(z.number()) })
const Container = z.object({ contentHash: z.string(), size: z.number(), path: z.string().nullable() })
const Prepared = z.object({
    skipped: z.array(z.object({ id: z.number(), reason: z.string() })),
    prepared: z.array(Container.extend({ id: z.number(), chunkId: z.string(), releaseId: z.string().nullable() })),
    duplicates: z.array(z.string()),
})
const CssCandidates = z.object({
    candidates: z.array(z.object({ id: z.number(), mapRealPath: z.string().nullable() }).nullable()),
})
const Cleaned = z.object({ deletedMaps: z.array(z.string()), warnings: z.array(z.string()) })
const ProguardContainer = z.union([z.object({ invalid: z.enum(['not_utf8', 'not_a_mapping']) }), Container])
const MapState = z.object({ id: z.number(), chunkId: z.string().nullable(), releaseId: z.string().nullable() })
export type MapState = z.output<typeof MapState>

const Maps = z.object({ maps: z.array(z.union([MapState, z.object({ unreadable: z.string() })])) })
const ClonedMap = z.object({ map: MapState })
const NativeProblem = z.enum(['no_debug_info', 'no_build_id', 'missing_uuid', 'compressed_dwarf', 'unparseable_slice'])
export type NativeProblem = z.output<typeof NativeProblem>

const NativeBinary = z.object({
    id: z.number(),
    debugId: z.string(),
    format: z.enum(['elf', 'macho']),
    size: z.number(),
})
export type NativeBinary = z.output<typeof NativeBinary>

const NativeFiles = z.object({
    files: z.array(
        z.union([
            z.object({ candidates: z.array(z.union([NativeBinary, z.object({ problem: NativeProblem })])) }),
            z.object({ unparseable: z.string() }),
        ])
    ),
})
const DsymMembers = z.object({
    members: z.array(
        z.union([
            z.object({ slices: z.array(z.object({ id: z.number(), uuid: z.string() })) }),
            z.object({ unreadable: z.string() }),
        ])
    ),
})
const SourcePaths = z.object({
    sources: z.array(z.union([z.object({ paths: z.array(z.string()) }), z.object({ failed: z.string() })])),
})
const Packed = z.object({
    unreadable: z.array(z.array(z.object({ path: z.string(), message: z.string() }))),
    containers: z.array(Container.nullable()),
})

export type InjectAction = z.output<typeof InjectAction>
export type InjectOutcome = z.output<typeof Outcomes>['outcomes'][number]
type PairAnswer = z.output<typeof Pairs>['pairs'][number]
type PreparedSymbolSets = z.output<typeof Prepared>
type CssCandidate = NonNullable<z.output<typeof CssCandidates>['candidates'][number]>
type CleanupReport = z.output<typeof Cleaned>
type ProguardContainer = z.output<typeof ProguardContainer>
export type MapAnswer = z.output<typeof Maps>['maps'][number]
type NativeFileAnswer = z.output<typeof NativeFiles>['files'][number]
type DsymMemberAnswer = z.output<typeof DsymMembers>['members'][number]
type SourcePathsAnswer = z.output<typeof SourcePaths>['sources'][number]
type PackedNative = z.output<typeof Packed>

export interface PackItem {
    id: number
    sources: number | null
    chunkId: string
    dsym: boolean
}

interface DetectCandidate {
    path: string
    bundle: boolean
    map: boolean
    mapping: boolean
    native: boolean
}

export interface Detected {
    sourcemap: Set<string>
    composed: Set<string>
    mapping: Set<string>
    elf: Set<string>
    macho: Set<string>
}

async function* readLines(stream: ReadableStream<Uint8Array>): AsyncGenerator<string> {
    const decoder = new TextDecoder()
    let buffered = ''
    for await (const chunk of stream) {
        const text = decoder.decode(chunk, { stream: true })
        let newline = text.indexOf('\n')
        if (newline < 0) {
            buffered += text
            continue
        }

        let start = 0
        while (newline >= 0) {
            yield buffered + text.slice(start, newline)
            buffered = ''
            start = newline + 1
            newline = text.indexOf('\n', start)
        }
        buffered = text.slice(start)
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

    constructor(
        private readonly path: string = workerPath({
            isDevelopment: FROM_SOURCE,
            execPath: process.execPath,
            platform: process.platform,
        }),
        private readonly build: Runtime['build'] = { version: VERSION, date: BUILD_DATE }
    ) {}

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
                    FROM_SOURCE
                        ? 'Run `pnpm --filter hog build:worker` to build it.'
                        : `hog-worker ships next to hog. ${upgradeHint(this.path)}`
                )
            }
            const lines = readLines(child.stdout)

            const first = await lines.next()
            const hello = first.done ? undefined : parseJsonOrUndefined(first.value, Hello)
            // A released hog and its worker carry one version. A dev build has only the protocol to compare.
            const released = this.build.date !== undefined
            const matches = released ? hello?.version === this.build.version : hello?.protocol === WORKER_PROTOCOL
            if (!hello || !matches) {
                child.kill()
                throw new HogError(
                    'worker_mismatch',
                    !hello
                        ? `The program at ${this.path} didn't answer like hog-worker.`
                        : released
                          ? `hog-worker ${hello.version} at ${this.path} isn't from this release of hog, ${this.build.version}.`
                          : `hog-worker ${hello.version} at ${this.path} speaks protocol ${hello.protocol}, and this hog needs protocol ${WORKER_PROTOCOL}.`,
                    `hog and hog-worker must come from the same release. ${upgradeHint(this.path)}`
                )
            }
            return { child, lines }
        })()
        return this.running
    }

    // `empty` answers a request whose list of ids, paths, files or items is empty, so it never starts the worker.
    private async call<T>(request: Record<string, unknown>, result: Schema<T>, empty?: T): Promise<T> {
        const list = request.ids ?? request.paths ?? request.files ?? request.items
        if (empty !== undefined && Array.isArray(list) && list.length === 0) {
            return empty
        }
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

    async detect(files: DetectCandidate[], publicPathPrefix: string | undefined): Promise<Detected> {
        const asked = files.filter((file) => file.bundle || file.map || file.mapping || file.native)
        const found = await this.call(
            { op: 'detect', files: asked, publicPathPrefix: publicPathPrefix ?? null },
            Detected,
            { sourcemap: [], composed: [], mapping: [], elf: [], macho: [] }
        )
        const paths = (indices: number[]): Set<string> => new Set(indices.map((index) => asked[index]!.path))
        return {
            sourcemap: paths(found.sourcemap),
            composed: paths(found.composed),
            mapping: paths(found.mapping),
            elf: paths(found.elf),
            macho: paths(found.macho),
        }
    }

    async readPairs(paths: string[], publicPathPrefix: string | undefined): Promise<PairAnswer[]> {
        return (
            await this.call({ op: 'read_pairs', paths, publicPathPrefix: publicPathPrefix ?? null }, Pairs, {
                pairs: [],
            })
        ).pairs
    }

    async drop(ids: number[]): Promise<void> {
        await this.call({ op: 'drop', ids }, Done, {})
    }

    async inject(ids: number[], mode: ReleaseMode, releaseId: string | null, now: number): Promise<InjectOutcome[]> {
        return (await this.call({ op: 'inject', ids, mode, releaseId, now }, Outcomes, { outcomes: [] })).outcomes
    }

    async save(ids: number[]): Promise<void> {
        await this.call({ op: 'save', ids }, Done, {})
    }

    async fingerprint(ids: number[]): Promise<number[]> {
        return (await this.call({ op: 'fingerprint', ids }, Targets, { targets: [] })).targets
    }

    async setRelease(held: { pairs?: number[]; maps?: number[] }, releaseId: string | null): Promise<void> {
        const { pairs = [], maps = [] } = held
        if (pairs.length > 0 || maps.length > 0) {
            await this.call({ op: 'set_release', pairs, maps, releaseId }, Done)
        }
    }

    // The worker lets the pairs go, so this is the last request that names them.
    async prepare(ids: number[], mode: ReleaseMode, folder: string | null): Promise<PreparedSymbolSets> {
        return this.call({ op: 'prepare', ids, mode, folder }, Prepared, { skipped: [], prepared: [], duplicates: [] })
    }

    async cssCandidates(files: string[], publicPathPrefix: string | undefined): Promise<CssCandidate[]> {
        const found = await this.call(
            { op: 'css_candidates', files, publicPathPrefix: publicPathPrefix ?? null },
            CssCandidates,
            { candidates: [] }
        )
        return found.candidates.filter((candidate) => candidate !== null)
    }

    async cleanUp(targets: number[], css: number[], roots: string[]): Promise<CleanupReport> {
        return this.call({ op: 'clean_up', targets, css, roots }, Cleaned)
    }

    async proguard(path: string, folder: string | null): Promise<ProguardContainer> {
        return this.call({ op: 'proguard', path, folder }, ProguardContainer)
    }

    async loadMaps(paths: string[]): Promise<MapAnswer[]> {
        return (await this.call({ op: 'load_maps', paths }, Maps, { maps: [] })).maps
    }

    async cloneMetadata(from: number, to: number): Promise<MapState> {
        return (await this.call({ op: 'clone_metadata', from, to }, ClonedMap)).map
    }

    async writeMaps(ids: number[]): Promise<void> {
        await this.call({ op: 'write_maps', ids }, Done, {})
    }

    async prepareMaps(ids: number[], folder: string | null): Promise<PreparedSymbolSets> {
        return this.call({ op: 'prepare_maps', ids, folder }, Prepared, { skipped: [], prepared: [], duplicates: [] })
    }

    async nativeCandidates(paths: string[]): Promise<NativeFileAnswer[]> {
        return (await this.call({ op: 'native_candidates', paths }, NativeFiles, { files: [] })).files
    }

    async dsymSlices(paths: string[]): Promise<DsymMemberAnswer[]> {
        return (await this.call({ op: 'dsym_slices', paths }, DsymMembers, { members: [] })).members
    }

    // A dSYM slice answers for its whole file.
    async sourcePaths(ids: number[]): Promise<SourcePathsAnswer[]> {
        return (await this.call({ op: 'source_paths', ids }, SourcePaths, { sources: [] })).sources
    }

    // The worker lets every binary go, so this is the last request that names one.
    async packNative(
        sources: string[][],
        items: PackItem[],
        folder: string | null,
        maxSize: number
    ): Promise<PackedNative> {
        return this.call({ op: 'pack_native', sources, items, folder, maxSize }, Packed, {
            unreadable: sources.map(() => []),
            containers: [],
        })
    }

    async check(): Promise<void> {
        try {
            await this.start()
        } finally {
            await this.close()
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

export function checkWorker(
    runtime: Pick<Runtime, 'isDevelopment' | 'execPath' | 'platform' | 'build'>
): Promise<void> {
    return new Worker(workerPath(runtime), runtime.build).check()
}

const workers = new WeakMap<Context, Worker>()

export function commandWorker(ctx: Context): Worker {
    let worker = workers.get(ctx)
    if (!worker) {
        const created = new Worker()
        ctx.onClose(() => created.close())
        workers.set(ctx, created)
        worker = created
    }
    return worker
}
