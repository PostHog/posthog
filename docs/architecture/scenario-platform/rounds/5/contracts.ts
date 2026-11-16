// Scenario platform contracts, reconciled after the Fable challenge (C1-C14). Throwaway: never imported.
// `Cn` marks a change a challenge forced; `Rn` marks a reopened question in the round 5 park.
import { z } from 'zod'

// ---------- shared ----------

/** Milliseconds since the epoch on the runner host's clock (round 2 Q6). */
export type HostMs = number
export type Status = 'passed' | 'failed' | 'invalid'
export type AdapterId = string // kebab-case; `-` becomes `_` in property names (C14.4)

/** A hook that cannot do its job throws. Core turns the throw into an `invalid` reason; no adapter returns a status. */
export class AdapterError extends Error {
    constructor(
        readonly adapter: AdapterId,
        readonly hook: 'build' | 'seed' | 'ready' | 'reset' | 'pending' | 'offer' | 'apply' | 'validAfter',
        message: string
    ) {
        super(`${adapter} ${hook}: ${message}`)
    }
}

/** Core constants, not per-adapter settings (C8). The Rust build sits outside reset (round 4 Q3 note). */
export const DEADLINES_MS = { build: 1_200_000, seed: 120_000, ready: 120_000, reset: 120_000, pending: 5_000 } as const

// ---------- 1. history (round 2 Q10, round 3 Q3, C7) ----------
// Only core writes it. Lines are NOT in clock order: offers are recorded after their answer and follow-up,
// outcomes arrive by polling (C7). Readers sort by `at` when order matters. `v` stays on every line, because the
// live tail and a store read lines independently.

export const Offer = z.object({
    v: z.literal(1),
    kind: z.literal('offer'),
    unit: z.string(),
    adapter: z.string(),
    traffic: z.string(),
    team: z.number().int(), // C3
    at: z.number(), // stamped before the offer is sent
    answeredAt: z.number(), // C7
    answer: z.union([
        z.object({ accepted: z.literal(true) }),
        z.object({ accepted: z.literal(false), status: z.number().optional(), error: z.string().optional() }),
    ]),
    expect: z.array(z.string()),
    /** Keys the tail may see for this unit, predicted at offer time, such as `{ person_id }` (C3). */
    carrier: z.record(z.string(), z.string()),
    /** A traffic kind's second step, such as the bounce follow-up `bounced_suppressed` reads (C7). */
    followUp: z.object({ at: z.number(), status: z.number().optional() }).optional(),
})

export const Outcome = z.object({
    v: z.literal(1),
    kind: z.literal('outcome'),
    /** Per-source sequence, as the edge's truth log has today (`provider-edge/truth.ts:56-58`) (C7). */
    seq: z.number().int(),
    key: z.string().optional(),
    delivery: z.string(),
    source: z.string(),
    at: z.number(),
    status: z.number().int(),
    fault: z.string().optional(),
    detail: z.unknown().optional(),
})

export const HistoryLine = z.discriminatedUnion('kind', [Offer, Outcome])
export type HistoryLine = z.infer<typeof HistoryLine>

/** A truth source beside the edge. Core pulls with an opaque cursor, never with a foreign clock (C7). */
export type TruthSource = {
    name: string
    read(cursor: string | undefined): Promise<{ outcomes: z.infer<typeof Outcome>[]; cursor: string }>
}

export interface History {
    append(line: HistoryLine): void // buffered, flushed each second and at phase ends (round 4 Q6)
    flush(): Promise<void>
    /** Joins outcomes to units through the offers' carriers. Any stray makes the run `invalid` (C3). */
    unitOf(outcome: z.infer<typeof Outcome>): string | 'stray' | undefined
}

// ---------- 2. manifest (round 2 Q8, C8, C9, C13) ----------
// Only `processes` is required. Everything else has a default, so a first adapter is one small file.

const Readiness = z.discriminatedUnion('kind', [
    z.object({ kind: z.literal('http'), path: z.string(), port: z.string() }),
    z.object({ kind: z.literal('tcp'), port: z.string() }),
    z.object({ kind: z.literal('log'), match: z.string() }),
    z.object({ kind: z.literal('exit'), code: z.number().int().default(0) }),
])

/** How core sees a process in the topology and in quiet (C4, C6). */
const Observe = z.discriminatedUnion('kind', [
    z.object({ kind: z.literal('group'), groups: z.array(z.string()) }), // lag read in one call for all groups
    z.object({
        kind: z.literal('client'),
        pgApplicationName: z.string().optional(),
        kafkaClientId: z.string().optional(),
    }),
    z.object({ kind: z.literal('metric'), metric: z.string() }), // a self-assigning consumer reports its own backlog
    z.object({ kind: z.literal('none') }),
])

/** Closed predicates: series against a constant or another series, combined with any/all (C10). */
const Compare = z.object({
    series: z.string(),
    op: z.enum(['>', '>=', '<', '<=', '==']),
    value: z.union([z.number(), z.object({ series: z.string() })]),
})
const Predicate = z.union([Compare, z.object({ any: z.array(Compare) }), z.object({ all: z.array(Compare) })])

/** The only state classes a look may use; core CSS owns them (C11). */
const NodeState = z.enum(['busy', 'down', 'faulted'])

export const Manifest = z.object({
    manifest: z.literal(1),
    adapter: z.string(),
    processes: z.record(
        z.string(),
        z.object({
            cmd: z.string(), // local only; CI and run-host commands wait for a second runner (C8)
            build: z.string().optional(), // `cargo build --bin …`, run once before the first reset (round 4 Q3 note)
            env: z.record(z.string(), z.string()).default({}),
            passEnv: z.array(z.string()).default([]), // round 2 Q9
            ports: z.array(z.string()).default([]),
            ready: Readiness,
            observe: Observe.default({ kind: 'none' }),
            /** Prometheus text endpoint; without it core still samples CPU, RSS and restarts by pid (C13). */
            metrics: z.object({ port: z.string(), path: z.string().default('/metrics') }).optional(),
        })
    ),
    resources: z.array(z.string()).default([]),
    links: z.array(z.object({ from: z.string(), to: z.string() })).default([]), // `carries` waits (C8)
    targets: z.record(z.string(), z.string()).default({}),
    /** Tier 0 names and their label keys (C10). Hashed into the adapter's version only through `series`
     * names a verdict reads; display-only series sit under `view` (C14.2). */
    series: z
        .record(
            z.string(),
            z.object({
                unit: z.string(),
                kind: z.enum(['gauge', 'rate', 'count']),
                labels: z.array(z.string()).default([]),
            })
        )
        .default({}),
    view: z
        .object({
            /** Display-only series an adapter derives at run time, so the page computes nothing (C10). */
            series: z
                .record(z.string(), z.object({ unit: z.string(), labels: z.array(z.string()).default([]) }))
                .default({}),
            panels: z
                .array(
                    z.object({
                        id: z.string(),
                        title: z.string(),
                        kind: z.enum(['line', 'stacked', 'stat']), // tables stay core: they read the verdict (C10)
                        series: z.array(z.string()),
                        slot: z.enum(['run', 'scenario', 'node']),
                    })
                )
                .default([]),
            nodes: z
                .record(
                    z.string(),
                    z.object({
                        shape: z.enum(['pod', 'cylinder', 'pill', 'topic']),
                        /** Typed parts, not free strings: `{ text }` or `{ series, fmt, when? }` (C10). */
                        lines: z
                            .array(
                                z.array(
                                    z.union([
                                        z.object({ text: z.string() }),
                                        z.object({
                                            series: z.string(),
                                            fmt: z.enum(['number', 'percent', 'ms', 'bytes']),
                                            when: Predicate.optional(),
                                        }),
                                    ])
                                )
                            )
                            .default([]),
                        states: z.array(z.object({ when: Predicate, state: NodeState, label: z.string() })).default([]),
                    })
                )
                .default({}),
            links: z
                .record(z.string(), z.object({ series: z.array(z.string()), bad: Predicate.optional() })) // summed (C10)
                .default({}),
            /** Plain sentences for findings, keyed by invariant name, with `{observed}` and `{gate}` slots (C10). */
            findings: z.record(z.string(), z.string()).default({}),
        })
        .prefault({}),
})
export type Manifest = z.infer<typeof Manifest>

// ---------- 3. valves and capabilities (round 2 Q2, C8) ----------

export interface Capabilities {
    processes: {
        kill(process: string): Promise<void>
        freeze(process: string): Promise<void>
        thaw(process: string): Promise<void>
    }
    postgres(resource: string): {
        dropConnections(share: number): Promise<number>
        failover?(holdMs: number, signal: AbortSignal): Promise<Actuation>
    }
    edge(host: string): { fault(rule: unknown): Actuation }
}

export type Actuation = {
    observed(holdEnds?: AbortSignal): Promise<boolean>
    release(): Promise<void>
    journal?(): Record<string, unknown>
}

export type ValveDefinition<P = unknown> = {
    name: string
    params: z.ZodType<P>
    target: 'process' | `db:${string}` | `host:${string}`
    /** One flag instead of a capability list (C8); load refuses the card off a run host (round 4 Q5). */
    runHostOnly?: true
    strandsRunningJobs: boolean
    /** Node state while the valve holds, with `{dose.*}` slots: `REJECTING {dose.type}` (C10). Core draws it. */
    label: string
    apply(caps: Capabilities, target: string, dose: P, holdMs: number, signal: AbortSignal): Promise<Actuation>
}

// ---------- 4. the adapter (C1, C2, C3, C5, C6, C9) ----------

export type Unit = { id: string; index: number; traffic: string; team: number } // C3

export type TrafficDefinition<P = unknown> = {
    name: string
    params: z.ZodType<P>
    carrier: string[]
    offer(
        unit: Unit,
        run: SeededRun,
        signal: AbortSignal
    ): Promise<Pick<z.infer<typeof Offer>, 'answer' | 'expect' | 'carrier' | 'followUp'>>
}

export type Check = { name: string; passed: boolean; reason: string }

/** What a seed hands downstream, such as a cohort id the tail's workflow triggers on (C2). */
export type Seeded = { teams: number[]; exports: Record<string, string | number> }
export type SeededRun = { runId: string; seeded: Record<AdapterId, Seeded> }

export type Pending = { work: Record<string, number> }

export interface Adapter {
    id: AdapterId
    owners: { team: string; reviewers?: string[] }
    manifest: Manifest
    traffic?: TrafficDefinition[] // the head adapter has one; middle and tail adapters may have none
    /** Called tail first. Clears this adapter's state. */
    reset(signal: AbortSignal): Promise<void>
    /** Throw = unknown, never 0 (round 3 Q4). Groups declared under `observe` are read by core; this adds the rest. */
    pending(signal: AbortSignal): Promise<Pending>

    // Everything below defaults (C9).
    /** Before processes start, head first, with upstream exports (C1, C2). Writes rows, starts nothing. */
    seed?(run: { runId: string; upstream: Record<AdapterId, Seeded> }, signal: AbortSignal): Promise<Seeded>
    /** After processes are ready, before drive: the run is invalid if any check fails (C1, round 3 Q2).
     * Persons-cohorts checks: the catalog covers the cohort, the live topic, the allowlist, and one canary
     * unit whose predicted person id matches the row capture wrote (C3). */
    ready?(run: SeededRun, signal: AbortSignal): Promise<Check[]>
    /** After quiet, before the verdict: invalidity found late, such as a writer interruption with no valve (C6). */
    validAfter?(run: SeededRun, history: readonly HistoryLine[], signal: AbortSignal): Promise<Check[]>
    terminal?(outcomes: z.infer<typeof Outcome>[]): boolean // default: 2xx, or 4xx outside 408/429
    definitions?: {
        valves?: ValveDefinition[]
        invariants?: { name: string; params: z.ZodType }[]
        measurements?: { name: string; params: z.ZodType }[]
        predicates?: { name: string; read(pending: Pending): boolean }[]
    }
    profileSchema?: z.ZodType
    checkCard?(card: unknown, profile: unknown): void
    /** Diagnostics only, never in the verdict (C5, R1): distinct units seen at each hop, where a hop can tell. */
    hops?(run: SeededRun, signal: AbortSignal): Promise<{ hop: string; units: number }[]>
}

// ---------- 5. lifecycle and verdict (C1, C4, C6) ----------
// Order: build → stop head first → reset tail first → seed head first → start tail first → ready → drive →
// release → quiet → validAfter → judge. Quiet: every `pending` is 0 and every declared group's lag is 0,
// held for the card's `settleMs` (default 2× the longest declared commit interval), plus every expected
// delivery recorded (C4). The status rule is today's `statusOf` order (`runner/status.ts:186-234`), with
// adapter checks joining the invalid list (C6).

export type Verdict = {
    status: Status
    reason: string
    invariants: {
        owner: AdapterId | 'core'
        name: string
        passed: boolean
        observed: number
        violation?: string
        units: string[]
    }[]
    hops?: { hop: string; units: number }[] // diagnostic (C5)
}

// ---------- 6. scorecard and versions (round 1 Q4, round 4 Q1, C8, C14) ----------

/** v2 adds fields; it renames nothing core owns (C8, R3). Adapter-owned invariants and measurements are prefixed. */
export type ScorecardV2 = {
    schema_version: 2
    adapters: AdapterId[]
    owners: string[]
    versions: Record<`core` | `adapters/${AdapterId}`, string>
    head_dirty: boolean // a dirty tree still hashes HEAD and says so, as today (C14.1)
} & Record<string, unknown> // v1 core keys unchanged: `inv_at_least_once_passed`, `m_delivery_latency_ms_p95`

/** One central include list in core (round 4 Q1 answer, C8): the paths that shape an outcome. A test fails on a
 * directory under `nodejs/tests/scenarios/` that is neither listed here nor in `NOT_OUTCOME`. */
export const OUTCOME_PATHS = [
    'core/lifecycle',
    'core/drive',
    'core/valves',
    'core/judge',
    'core/processes',
    'core/edge',
] as const
export const NOT_OUTCOME = ['core/viewer', 'core/store', 'core/cli'] as const
// An adapter's version hashes its directory minus `manifest.yaml`'s `view` key (C14.2).

// ---------- 7. viewer (round 2 Q11, C10-C13) ----------

/** Tier 0, with labels, so one name covers every role (C10). */
export type Series = {
    adapter: AdapterId
    name: string
    labels: Record<string, string>
    unit: string
    points: [HostMs, number | null][]
}

export type RunRecord = {
    scorecard: ScorecardV2
    history: HistoryLine[]
    series: Series[]
    topology: unknown
    manifests: Manifest[]
    timeline: { valve: string; target: string; label: string; from: HostMs | null; to: HostMs | null; error?: string }[]
}

// Core owns, for every adapter with no UI code (C10, C13): the verdict, the end-to-end panels from history,
// the valve timeline and its node states, stale ("not answering") and stopped (killed, frozen) rendering,
// per-process CPU, RSS, restarts and group lag with a default look, and the findings list.
// Composition (C12): the card's adapter order drives map columns and panel groups; two looks for one shared
// resource are a load error; adapters upstream of the card's tail start collapsed.
// Tier 2 stays a sentence in the spec, with no published type, and the server serves no adapter code (C11).
