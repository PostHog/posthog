/**
 * Per-element framework overhead. The steps do trivial work (`v + 1`), so the numbers are the
 * cost of the framework itself. The workloads and sizes match
 * `rust/ingestion-framework/benches/framework.rs`, so the two can be compared.
 *
 * Run from `nodejs/`. The config module needs a database URL at import time; nothing connects:
 * `DATABASE_URL=postgres://localhost/bench pnpm exec tsx src/ingestion/framework/benchmarks/framework-bench.ts`
 * Prints one JSON line per workload and size with the mean ns per element.
 */
import {
    newBatchingPipeline,
    newChunkPipelineBuilder,
    newPipelineBuilder,
    perElement,
} from '~/ingestion/framework/builders'
import { createOkContext } from '~/ingestion/framework/helpers'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

const SIZES = [1, 100, 10_000]
const MIN_BENCH_MS = Number(process.env.BENCH_MS ?? 2000)

type Ctx = Record<string, never>

function inc(name: string): ProcessingStep<number, number> {
    const step: ProcessingStep<number, number> = (v) => Promise.resolve(ok(v + 1))
    Object.defineProperty(step, 'name', { value: name })
    return step
}

function incChunk(name: string): (values: number[]) => Promise<ReturnType<typeof ok<number>>[]> {
    const step = (values: number[]): Promise<ReturnType<typeof ok<number>>[]> =>
        Promise.resolve(values.map((v) => ok(v + 1)))
    Object.defineProperty(step, 'name', { value: name })
    return step
}

function inputs(n: number): ReturnType<typeof createOkContext<number, Ctx>>[] {
    const out = new Array(n)
    for (let i = 0; i < n; i++) {
        out[i] = createOkContext<number, Ctx>(i, {})
    }
    return out
}

async function drain(pipeline: { next(): Promise<unknown[] | null> }): Promise<number> {
    let count = 0
    let chunk = await pipeline.next()
    while (chunk !== null) {
        count += chunk.length
        chunk = await pipeline.next()
    }
    return count
}

const stepPipeline = newPipelineBuilder<number, Ctx>()
    .pipe(inc('s1'))
    .pipe(inc('s2'))
    .pipe(inc('s3'))
    .pipe(inc('s4'))
    .pipe(inc('s5'))
    .build()

const WORKLOADS: Record<string, (n: number) => Promise<void>> = {
    step_pipeline_5_steps: async (n) => {
        for (const input of inputs(n)) {
            await stepPipeline.process(input)
        }
    },
    pipe_chunk_5_steps: async (n) => {
        const pipeline = newChunkPipelineBuilder<number, Ctx>()
            .pipeChunk(incChunk('c1'))
            .pipeChunk(incChunk('c2'))
            .pipeChunk(incChunk('c3'))
            .pipeChunk(incChunk('c4'))
            .pipeChunk(incChunk('c5'))
            .build()
        pipeline.feed(inputs(n))
        assertCount(await drain(pipeline), n)
    },
    concurrently_max50: async (n) => {
        const pipeline = newChunkPipelineBuilder<number, Ctx>()
            .concurrently((b) => b.pipe(inc('s1')).pipe(inc('s2')), { maxConcurrency: 50 })
            .build()
        pipeline.feed(inputs(n))
        assertCount(await drain(pipeline), n)
    },
    per_element_max50: async (n) => {
        const pipeline = newChunkPipelineBuilder<number, Ctx>()
            .pipeChunk(perElement(inc('s1'), { maxConcurrency: 50 }))
            .pipeChunk(perElement(inc('s2'), { maxConcurrency: 50 }))
            .build()
        pipeline.feed(inputs(n))
        assertCount(await drain(pipeline), n)
    },
    concurrently_per_group_16: async (n) => {
        const pipeline = newChunkPipelineBuilder<number, Ctx>()
            .concurrentlyPerGroup(
                (v) => v % 16,
                (g) => g.sequentially((b) => b.pipe(inc('s1')).pipe(inc('s2')))
            )
            .build()
        pipeline.feed(inputs(n))
        assertCount(await drain(pipeline), n)
    },
    batching_full: async (n) => {
        type V = number & { batchId?: number }
        const pipeline = newBatchingPipeline<number, V, Ctx>(
            (b) =>
                b.pipe(function before(input) {
                    return Promise.resolve(ok({ elements: input.elements, batchContext: input.batchContext }))
                }),
            (b) =>
                b
                    .pipeChunk(function prepare(values: V[]) {
                        return Promise.resolve(values.map((v) => ok(v + 1)))
                    })
                    .concurrentlyPerGroup(
                        (v: V) => v % 16,
                        (g) =>
                            g.sequentially((s) =>
                                s.pipe(function work(v: V) {
                                    return Promise.resolve(ok(v + 1))
                                })
                            ),
                        { maxConcurrency: 50 }
                    )
                    .gather(),
            (b) =>
                b.pipe(function after(input) {
                    return Promise.resolve(ok(input))
                }),
            { concurrentBatches: 1 }
        )
        const fed = await pipeline.feed(inputs(n), {})
        if (!fed.ok) {
            throw new Error(`feed rejected: ${fed.reason}`)
        }
        const done = await pipeline.next()
        assertCount(done!.elements.length, n)
    },
}

function assertCount(actual: number, expected: number): void {
    if (actual !== expected) {
        throw new Error(`expected ${expected} results, got ${actual}`)
    }
}

async function bench(name: string, n: number, run: (n: number) => Promise<void>): Promise<void> {
    // Warm up the JIT before timing.
    const warmupUntil = performance.now() + Math.min(500, MIN_BENCH_MS / 4)
    while (performance.now() < warmupUntil) {
        await run(n)
    }
    let iterations = 0
    const started = process.hrtime.bigint()
    const deadline = performance.now() + MIN_BENCH_MS
    while (performance.now() < deadline) {
        await run(n)
        iterations++
    }
    const elapsedNs = Number(process.hrtime.bigint() - started)
    const nsPerElement = elapsedNs / (iterations * n)
    console.log(
        JSON.stringify({
            impl: 'node',
            workload: name,
            size: n,
            iterations,
            ns_per_element: Math.round(nsPerElement),
            elements_per_sec: Math.round(1e9 / nsPerElement),
        })
    )
}

async function main(): Promise<void> {
    const only = process.argv[2]
    for (const [name, run] of Object.entries(WORKLOADS)) {
        if (only && !name.includes(only)) {
            continue
        }
        for (const n of SIZES) {
            await bench(name, n, run)
        }
    }
}

void main().then(
    () => process.exit(0),
    (error) => {
        console.error(error)
        process.exit(1)
    }
)
