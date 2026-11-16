// Scenario platform contracts, round 4 sketch. Throwaway: never imported, never merged.
// Each section is one locked seam. `Qn` marks a part this round asks about.
import { z } from 'zod'

// ---------- shared ----------

/** Milliseconds since the epoch on the runner host's clock (round 2 Q6). */
export type HostMs = number
export type Status = 'passed' | 'failed' | 'invalid'
export type AdapterId = string // kebab-case, unique across the tree: `workflows`, `persons-cohorts`

/** A hook that cannot do its job throws. Core turns the throw into a reason; no adapter returns a status. */
export class AdapterError extends Error {
    constructor(
        readonly adapter: AdapterId,
        readonly hook: 'prepare' | 'reset' | 'pending' | 'counts' | 'offer' | 'apply',
        message: string
    ) {
        super(`${adapter} ${hook}: ${message}`)
    }
}

// ---------- 1. history (round 2 Q10, round 3 Q3) ----------
// The one file a run writes and every judge, viewer and foreign harness reads.
// Invariants: only core writes it; lines are appended in host-clock order; `v` is on every line.

export const Offer = z.object({
    v: z.literal(1),
    kind: z.literal('offer'),
    unit: z.string(),
    adapter: z.string(),
    traffic: z.string(),
    at: z.number(),
    answer: z.union([
        z.object({ accepted: z.literal(true) }),
        z.object({ accepted: z.literal(false), status: z.number().optional(), error: z.string().optional() }),
    ]),
    /** Delivery kinds the unit must reach, such as `webhook`. */
    expect: z.array(z.string()),
    /** Every key the tail may see for this unit, such as `{ person_id }`. The judge joins outcomes on these. */
    carrier: z.record(z.string(), z.string()),
})

export const Outcome = z.object({
    v: z.literal(1),
    kind: z.literal('outcome'),
    /** The raw correlation value the source parsed: a path segment, a recipient, a header. */
    key: z.string().optional(),
    delivery: z.string(),
    source: z.string(), // `edge:webhook`, `edge:ses`, or a truth source an adapter registers
    at: z.number(),
    status: z.number().int(),
    fault: z.string().optional(),
    detail: z.unknown().optional(),
})

export const HistoryLine = z.discriminatedUnion('kind', [Offer, Outcome])
export type HistoryLine = z.infer<typeof HistoryLine>

export interface History {
    /** Buffered; flushed every second and at each phase end (Q6). Never throws on a slow disk: it backs up. */
    append(line: HistoryLine): void
    flush(): Promise<void>
    /** The judge's join, built from offers (round 3 Q3). An outcome whose key no offer carries is `stray`. */
    unitOf(outcome: z.infer<typeof Outcome>): string | 'stray' | undefined
}

// ---------- 2. manifest (round 2 Q8, round 3 Q8) ----------
// One YAML file per adapter, parsed by core. Every name a view part uses must be declared here.

const Readiness = z.discriminatedUnion('kind', [
    z.object({ kind: z.literal('http'), path: z.string(), port: z.string() }),
    z.object({ kind: z.literal('tcp'), port: z.string() }),
    z.object({ kind: z.literal('log'), match: z.string() }),
    z.object({ kind: z.literal('exit'), code: z.number().int().default(0) }),
])

const Predicate = z.object({ series: z.string(), op: z.enum(['>', '>=', '<', '<=', '==']), value: z.number() })

export const Manifest = z.object({
    manifest: z.literal(1), // Q7
    adapter: z.string(),
    processes: z.record(
        z.string(),
        z.object({
            cmd: z.object({ local: z.string(), ci: z.string().optional(), host: z.string().optional() }),
            mode: z.string().optional(),
            env: z.record(z.string(), z.string()).default({}),
            /** Allowed through from the shell by name; nothing else is (round 2 Q9). */
            passEnv: z.array(z.string()).default([]),
            ports: z.array(z.string()).default([]),
            ready: Readiness,
            labels: z.object({ pgApplicationName: z.string().optional(), kafkaClientId: z.string().optional() }),
            copies: z.number().int().min(1).default(1),
        })
    ),
    /** Stable ids: `topic:clickhouse_events_json`, `db:cyclotron`, `host:ses`. Shared ids merge across adapters. */
    resources: z.array(z.string()),
    links: z.array(
        z.object({ from: z.string(), to: z.string(), via: z.string().optional(), carries: z.array(z.string()) })
    ),
    /** Valve target aliases: `cyclotron: db:cyclotron`. */
    targets: z.record(z.string(), z.string()).default({}),
    text: z.record(z.string(), z.string()).default({}),
    /** Per-hook deadlines in ms; core aborts the hook's signal and reports an AdapterError (Q3). */
    deadlines: z
        .object({ reset: z.number(), prepare: z.number(), pending: z.number(), counts: z.number() })
        .default({ reset: 120_000, prepare: 120_000, pending: 5_000, counts: 30_000 }),
    /** Tier 0 names this adapter may emit, with their unit. Undeclared names fail the load (round 3 Q8). */
    series: z.record(z.string(), z.object({ unit: z.string(), kind: z.enum(['gauge', 'rate', 'count']) })),
    view: z.object({
        panels: z.array(
            z.object({
                id: z.string(),
                title: z.string(),
                kind: z.enum(['line', 'stacked', 'stat', 'table']),
                series: z.array(z.string()),
                slot: z.enum(['run', 'scenario', 'node']),
            })
        ),
        nodes: z.record(
            z.string(),
            z.object({
                shape: z.enum(['pod', 'cylinder', 'pill', 'topic']),
                /** `{series}` or `{series|fmt}` placeholders; no expressions (Q8). */
                lines: z.array(z.string()).default([]),
                states: z.array(z.object({ when: Predicate, className: z.string(), label: z.string() })).default([]),
            })
        ),
        linkRates: z.record(z.string(), z.object({ series: z.string(), bad: Predicate.optional() })).default({}),
    }),
})
export type Manifest = z.infer<typeof Manifest>

// ---------- 3. valves and capabilities (round 2 Q2) ----------

export type Capability = 'processes' | 'postgres' | 'edge' | 'aws'

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
    aws?: unknown // run host only
}

export type Actuation = {
    observed(holdEnds?: AbortSignal): Promise<boolean>
    release(): Promise<void>
    journal?(): Record<string, unknown>
}

export type ValveDefinition<P = unknown> = {
    name: string // `process.kill`, `ses.reject`
    params: z.ZodType<P>
    /** A manifest resource kind or alias the target must resolve to. Checked at load. */
    target: 'process' | `db:${string}` | `host:${string}`
    /** Load refuses a card whose host lacks one (Q5): no more "runs only on a run host" at apply. */
    requires: Capability[]
    strandsRunningJobs: boolean
    apply(caps: Capabilities, target: string, dose: P, holdMs: number, signal: AbortSignal): Promise<Actuation>
}

// ---------- 4. the adapter (round 2 Q1, Q3, Q4, Q7; round 3 Q4, Q5, Q6) ----------

export type Unit = { id: string; index: number; traffic: string }

export type OfferResult = Pick<z.infer<typeof Offer>, 'answer' | 'expect' | 'carrier'>

export type TrafficDefinition<P = unknown> = {
    name: string
    params: z.ZodType<P>
    /** How the unit id reaches the tail; every link on the path must carry one of these (round 2 Q4). */
    carrier: string[]
    /** Called by drive at the scheduled time. Core writes the history line; the adapter never does (Q4). */
    offer(unit: Unit, run: PreparedRun, signal: AbortSignal): Promise<OfferResult>
}

export type Prepared = {
    seed?: unknown
    /** Validity checks that must pass before drive (round 3 Q2). A failed one makes the run invalid. */
    validity: { name: string; passed: boolean; reason: string }[]
    /** Truth sources beside the edge, appended to history by core. */
    sources?: { name: string; read(since: HostMs): Promise<z.infer<typeof Outcome>[]> }[]
}

export type PreparedRun = { runId: string; teamIds: number[]; prepared: Record<AdapterId, Prepared> }

export type Pending = { work: Record<string, number> } // all zero = this adapter is quiet

export type Counts = { hop: string; count: number }[] // in path order (round 3 Q5)

export interface Adapter {
    id: AdapterId
    owners: { team: string; reviewers?: string[] }
    manifest: Manifest
    definitions: {
        traffic: TrafficDefinition[]
        valves: ValveDefinition[]
        invariants: { name: string; params: z.ZodType }[]
        measurements: { name: string; params: z.ZodType }[]
        bars: { name: string; params: z.ZodType }[]
        predicates: { name: string; read(pending: Pending): boolean }[]
    }
    profileSchema: z.ZodType
    /** Pure. Throws a load error naming the card field. */
    checkCard(card: unknown, profile: unknown): void

    // Required run hooks. Each gets a deadline from core (Q3); a throw or a timeout is an AdapterError.
    reset(signal: AbortSignal): Promise<void>
    /** Called each second while quiet is awaited and by valve predicates. Throw = unknown, never 0 (round 3 Q4). */
    pending(signal: AbortSignal): Promise<Pending>

    // Optional hooks (Q2).
    prepare?(run: { runId: string; teamIds: number[] }, signal: AbortSignal): Promise<Prepared>
    /** Needed only when the card names a `conservation` invariant over this adapter. */
    counts?(run: PreparedRun, signal: AbortSignal): Promise<Counts>
    /** Which outcomes end a delivery for good. Default: any 2xx or a 4xx outside 408/429. */
    terminal?(outcomes: z.infer<typeof Outcome>[]): boolean
}

// ---------- 5. lifecycle and verdict (round 3 Q2, Q6) ----------

export type Verdict = {
    status: Status
    reason: string
    invariants: {
        adapter: AdapterId | 'core'
        name: string
        passed: boolean
        observed: number
        violation?: string
        units: string[]
    }[]
    /** First adjacent pair whose count drops, when conservation fails (round 3 Q5). */
    ledgerDrop?: { from: Counts[number]; to: Counts[number] }
}

export interface Lifecycle {
    /** Never throws for a run that started: every failure becomes an invalid or failed verdict with a reason. */
    run(
        cardPath: string,
        signal: AbortSignal
    ): Promise<{ verdict: Verdict; record: RunRecord; exitCode: 0 | 1 | 2 | 3 }>
}

// ---------- 6. scorecard v2 and the publisher (round 1 Q2, Q4) ----------

export type ScorecardV2 = {
    schema_version: 2
    run_id: string
    status: Status
    adapters: AdapterId[]
    owners: string[]
    /** `${adapterId}:${treeSha}` per adapter plus `core:${treeSha}`; the fingerprint hashes these. */
    versions: Record<string, string | null>
} & Record<`${AdapterId}__inv_${string}` | `${AdapterId}__m_${string}`, string | number | boolean | null | string[]>

/** `scenarios publish <file>`: a foreign harness writes a run record; this builds the same payload a run would. */
export type PayloadOf = (record: RunRecord) => ScorecardV2

// ---------- 7. viewer (round 2 Q11, round 3 Q7, Q8) ----------

/** Tier 0. */
export type Series = {
    adapter: AdapterId
    name: string
    unit: string
    kind: 'gauge' | 'rate' | 'count'
    points: [HostMs, number | null][]
}

/** All the viewer needs, whatever RunSource delivers it. A v1 record is converted on read (round 3 Q7). */
export type RunRecord = {
    scorecard: ScorecardV2
    history: HistoryLine[]
    series: Series[]
    topology: unknown // #136528's Topology, rows keyed by (adapter, role)
    manifests: Manifest[] // merged view: shared resource ids collapse, node ids become `${adapter}:${id}`
    timeline: { valve: string; target: string; from: HostMs | null; to: HostMs | null; error?: string }[]
}

/** Tier 2, named and not built (round 1 Q6). No clock inside, so it replays. */
export type PanelContext = {
    run: RunRecord
    series(name: string): Series | undefined
    theme: 'light' | 'dark'
    selectNode(id: string): void
}
export type PanelSlot = (root: ShadowRoot, ctx: PanelContext, t: HostMs) => void
