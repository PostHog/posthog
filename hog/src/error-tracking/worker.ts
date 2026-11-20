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
const Prepared = z.object({
    prepared: z.array(
        z.union([
            z.object({ skipped: z.string() }),
            z.object({
                chunkId: z.string(),
                releaseId: z.string().nullable(),
                contentHash: z.string(),
                size: z.number(),
                path: z.string().nullable(),
            }),
        ])
    ),
})
const CssCandidates = z.object({
    candidates: z.array(z.object({ id: z.number(), mapRealPath: z.string().nullable() }).nullable()),
})
const Cleaned = z.object({ deletedMaps: z.array(z.string()), warnings: z.array(z.string()) })
const ProguardContainer = z.union([
    z.object({ invalid: z.enum(['not_utf8', 'not_a_mapping']) }),
    z.object({ contentHash: z.string(), size: z.number() }),
])
const MapState = z.object({
    id: z.number(),
    chunkId: z.string().nullable(),
    debugId: z.string().nullable(),
    releaseId: z.string().nullable(),
    empty: z.boolean(),
})
export type MapState = z.output<typeof MapState>

const Maps = z.object({ maps: z.array(z.union([MapState, z.object({ unreadable: z.string() })])) })
const ClonedMap = z.object({ map: MapState })
const MapContainers = z.object({
    containers: z.array(
        z.object({
            contentHash: z.string(),
            size: z.number(),
            path: z.string().nullable(),
        })
    ),
})
const NativeProblem = z.enum(['no_debug_info', 'no_build_id', 'missing_uuid', 'compressed_dwarf', 'unparseable_slice'])
export type NativeProblem = z.output<typeof NativeProblem>

const NativeBinary = z.object({
    id: z.number(),
    debugId: z.string(),
    format: z.enum(['elf', 'macho']),
    size: z.number(),
})
// One ELF or Mach-O binary with debug info and an ID, held by the worker. A fat Mach-O gives one
// for each architecture.
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
const NativeContainer = z.object({
    contentHash: z.string(),
    size: z.number(),
    // Null in a dry run, which writes nothing.
    path: z.string().nullable(),
})
const Packed = z.object({
    unreadable: z.array(z.array(z.object({ path: z.string(), message: z.string() }))),
    containers: z.array(NativeContainer),
})
const Wrapped = z.object({ contentHash: z.string(), size: z.number() })

export type InjectOutcome = z.output<typeof Outcomes>['outcomes'][number]
export type PairAnswer = z.output<typeof Pairs>['pairs'][number]
export type PreparedPair = z.output<typeof Prepared>['prepared'][number]
export type CssCandidate = NonNullable<z.output<typeof CssCandidates>['candidates'][number]>
export type CleanupReport = z.output<typeof Cleaned>
export type ProguardContainer = z.output<typeof ProguardContainer>
export type MapAnswer = z.output<typeof Maps>['maps'][number]
export type MapContainer = z.output<typeof MapContainers>['containers'][number]
export type NativeFileAnswer = z.output<typeof NativeFiles>['files'][number]
export type DsymMemberAnswer = z.output<typeof DsymMembers>['members'][number]
export type SourcePathsAnswer = z.output<typeof SourcePaths>['sources'][number]
export type PackedNative = z.output<typeof Packed>
export type NativeContainer = z.output<typeof NativeContainer>
export type WrappedPayload = z.output<typeof Wrapped>

// A binary to pack, with its place in the request's lists of source files. Null packs it alone.
export interface PackItem {
    id: number
    sources: number | null
}

export type ContainerKind = 'proguard' | 'hermes' | 'dsym' | 'elf'

export interface DetectCandidate {
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

    // Which files discovery counts: bundles whose sourcemap exists, maps the Hermes compiler
    // composed, ProGuard mappings, and ELF and Mach-O files. Every answer needs the file's contents.
    async detect(files: DetectCandidate[], publicPathPrefix: string | undefined): Promise<Detected> {
        const asked = files.filter((file) => file.bundle || file.map || file.mapping || file.native)
        if (asked.length === 0) {
            return { sourcemap: new Set(), composed: new Set(), mapping: new Set(), elf: new Set(), macho: new Set() }
        }
        const found = await this.call(
            { op: 'detect', files: asked, publicPathPrefix: publicPathPrefix ?? null },
            Detected
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

    async fingerprint(ids: number[]): Promise<number[]> {
        if (ids.length === 0) {
            return []
        }
        return (await this.call({ op: 'fingerprint', ids }, Targets)).targets
    }

    async setRelease(ids: number[], releaseId: string): Promise<void> {
        if (ids.length > 0) {
            await this.call({ op: 'set_release', ids, releaseId }, Done)
        }
    }

    // The worker lets the pairs go, so this is the last request that names them.
    async prepare(ids: number[], mode: 'event' | 'symbol-set', folder: string | null): Promise<PreparedPair[]> {
        if (ids.length === 0) {
            return []
        }
        return (await this.call({ op: 'prepare', ids, mode, folder }, Prepared)).prepared
    }

    async cssCandidates(files: string[], publicPathPrefix: string | undefined): Promise<CssCandidate[]> {
        if (files.length === 0) {
            return []
        }
        const found = await this.call(
            { op: 'css_candidates', files, publicPathPrefix: publicPathPrefix ?? null },
            CssCandidates
        )
        return found.candidates.filter((candidate) => candidate !== null)
    }

    async cleanUp(targets: number[], css: number[], roots: string[]): Promise<CleanupReport> {
        return this.call({ op: 'clean_up', targets, css, roots }, Cleaned)
    }

    async proguard(path: string, out: string | null): Promise<ProguardContainer> {
        return this.call({ op: 'proguard', path, out }, ProguardContainer)
    }

    async loadMaps(paths: string[]): Promise<MapAnswer[]> {
        if (paths.length === 0) {
            return []
        }
        return (await this.call({ op: 'load_maps', paths }, Maps)).maps
    }

    async cloneMetadata(from: number, to: number): Promise<MapState> {
        return (await this.call({ op: 'clone_metadata', from, to }, ClonedMap)).map
    }

    async setMapRelease(ids: number[], releaseId: string | null): Promise<void> {
        if (ids.length > 0) {
            await this.call({ op: 'set_map_release', ids, releaseId }, Done)
        }
    }

    async writeMaps(ids: number[]): Promise<void> {
        if (ids.length > 0) {
            await this.call({ op: 'write_maps', ids }, Done)
        }
    }

    async prepareMaps(ids: number[], folder: string | null): Promise<MapContainer[]> {
        if (ids.length === 0) {
            return []
        }
        return (await this.call({ op: 'prepare_maps', ids, folder }, MapContainers)).containers
    }

    // What each ELF or Mach-O file holds: its binaries, and the problems that keep others out.
    async nativeCandidates(paths: string[]): Promise<NativeFileAnswer[]> {
        if (paths.length === 0) {
            return []
        }
        return (await this.call({ op: 'native_candidates', paths }, NativeFiles)).files
    }

    // The architectures of each file inside a dSYM bundle, with their UUIDs.
    async dsymSlices(paths: string[]): Promise<DsymMemberAnswer[]> {
        if (paths.length === 0) {
            return []
        }
        return (await this.call({ op: 'dsym_slices', paths }, DsymMembers)).members
    }

    // The source files the DWARF of each binary names. A dSYM slice answers for its whole file.
    async sourcePaths(ids: number[]): Promise<SourcePathsAnswer[]> {
        if (ids.length === 0) {
            return []
        }
        return (await this.call({ op: 'source_paths', ids }, SourcePaths)).sources
    }

    // Builds the symbol set of each binary and writes it into `folder`, with the source files of
    // the list the item names. The worker lets every binary go, so this is the last request that
    // names one. Without a folder nothing is written.
    async packNative(sources: string[][], items: PackItem[], folder: string | null): Promise<PackedNative> {
        if (items.length === 0) {
            return { unreadable: sources.map(() => []), containers: [] }
        }
        return this.call({ op: 'pack_native', sources, items, folder }, Packed)
    }

    // Puts the bytes of a file into a container of one type, as they are.
    async wrap(path: string, kind: ContainerKind, out: string | null): Promise<WrappedPayload> {
        return this.call({ op: 'wrap', path, kind, out }, Wrapped)
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
