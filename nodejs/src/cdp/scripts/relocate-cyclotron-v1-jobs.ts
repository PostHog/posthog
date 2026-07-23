/**
 * One-shot operator script to empty the cyclotron V1 (legacy postgres) backend of a
 * single queue's parked jobs so V1 can be decommissioned without waiting ~90 days for
 * natural drain.
 *
 * For the target queue (default `hogflow`) it:
 *   - relocates every `available` job whose `scheduled` is within the next year into V2,
 *     preserving the original id and scheduled time, then deletes those rows from V1;
 *   - deletes the "corrupt" rows (`scheduled` more than a year out — a delay-overflow bug
 *     parked them so far in the future they never come due, so they never self-drain).
 *
 * Safety: a V1 row is the ONLY copy of that workflow run (the durable run-state lives in
 * the job payload, not a separate table), and cyclotron deletes are unrecoverable. So the
 * order is strictly write-to-V2 -> verify each id is present in V2 -> only then delete
 * those same ids from V1. Corrupt rows are only ever deleted, never relocated.
 *
 * Idempotent: V2 writes use `overwriteExisting: true` with the original id, and the delete
 * gate is verification (not "did this run write it"), so a re-run after a partial failure
 * finishes the job. Once a queue is fully drained a re-run is a no-op.
 *
 * Dry-run by default — pass `--apply` to actually write and delete.
 *
 * IMPORTANT: the legacy drain worker for the target queue MUST be scaled to 0 before this
 * runs, or the worker and this script can grab the same job (double execution / double
 * send).
 *
 * Usage:
 *   CYCLOTRON_V1_DATABASE_URL=... CYCLOTRON_V2_DATABASE_URL=... \
 *     tsx src/cdp/scripts/relocate-cyclotron-v1-jobs.ts --env prod-us [--queue hogflow] [--apply]
 */
import { Pool } from 'pg'
import zlib from 'zlib'

import { CyclotronJob } from '@posthog/cyclotron'

import { parseJSON } from '~/common/utils/json-parse'

import { CdpConfig } from '../config'
import { CyclotronJobConflictError } from '../services/cyclotron-v2'
import { cyclotronJobToInvocation } from '../services/job-queue/job-queue-postgres'
import { CyclotronJobQueuePostgresV2 } from '../services/job-queue/job-queue-postgres-v2'
import { CyclotronJobInvocation } from '../types'

// Rows scheduled further out than this are the "corrupt" ones — a delay-overflow bug
// parked them ~year 29405 so they never come due. They are deleted, never relocated.
const CORRUPT_CUTOFF_INTERVAL = "interval '1 year'"

// gzip streams start with `1f 8b 08` (ID1, ID2, CM=deflate). Only vm_state is ever
// compressed (and only when CDP_CYCLOTRON_COMPRESS_VM_STATE is on — off in prod), but we
// decode defensively so the script is correct regardless of that flag's history.
const GZIP_MAGIC = [0x1f, 0x8b, 0x08]

export interface RelocateArgs {
    queue: string
    envLabel: string
    apply: boolean
}

export interface CliArgs extends RelocateArgs {
    v1Url: string
    v2Url: string
}

export interface V1Row {
    id: string
    team_id: number
    function_id: string | null
    queue_name: string
    priority: number
    parent_run_id: string | null
    vm_state: Buffer | null
    metadata: Buffer | null
    parameters: Buffer | null
    blob: Buffer | null
    scheduled: Date | null
    scheduled_raw: string | null
    is_corrupt: boolean
}

/** The producer side of the V2 queue this script depends on — narrowed for injection in tests. */
export type V2Producer = Pick<CyclotronJobQueuePostgresV2, 'startAsProducer' | 'stopProducer' | 'queueInvocations'>

export interface RelocateDeps {
    /** V1 (legacy postgres) pool — source, gets emptied. */
    v1: Pick<Pool, 'query'>
    /** V2 (cyclotron-node) pool — used only to verify writes landed before deleting from V1. */
    v2Pool: Pick<Pool, 'query'>
    /** V2 producer — where legit jobs are relocated to. */
    v2Queue: V2Producer
    log?: (msg: string) => void
}

export interface RelocateResult {
    legitCount: number
    corruptCount: number
    /** Ids confirmed present in V2 and therefore deleted from V1. */
    verifiedIds: string[]
    /** Legit ids NOT confirmed in V2 — deliberately left in V1. */
    missingIds: string[]
    /** Rows actually deleted from V1 for the relocated (verified) set. */
    relocated: number
    /** Corrupt rows deleted from V1. */
    deletedCorrupt: number
    /** Remaining `available` rows for the queue in V1 after the run (0 when fully drained). */
    remaining: number
    applied: boolean
}

export function parseArgs(argv: string[]): CliArgs {
    const get = (flag: string): string | undefined => {
        const idx = argv.indexOf(flag)
        return idx !== -1 ? argv[idx + 1] : undefined
    }

    const v1Url = get('--v1-url') ?? process.env.CYCLOTRON_V1_DATABASE_URL ?? process.env.CYCLOTRON_DATABASE_URL
    const v2Url = get('--v2-url') ?? process.env.CYCLOTRON_V2_DATABASE_URL ?? process.env.CYCLOTRON_NODE_DATABASE_URL

    if (!v1Url) {
        throw new Error('V1 database URL missing — pass --v1-url or set CYCLOTRON_V1_DATABASE_URL')
    }
    if (!v2Url) {
        throw new Error('V2 database URL missing — pass --v2-url or set CYCLOTRON_V2_DATABASE_URL')
    }

    return {
        queue: get('--queue') ?? 'hogflow',
        envLabel: get('--env') ?? get('--region') ?? 'unspecified',
        apply: argv.includes('--apply'),
        v1Url,
        v2Url,
    }
}

/** Strip credentials from a postgres URL so it's safe to print. */
export function describeUrl(url: string): string {
    try {
        const parsed = new URL(url)
        const db = parsed.pathname.replace(/^\//, '') || '(default)'
        return `${parsed.hostname}:${parsed.port || '5432'}/${db}`
    } catch {
        return '(unparseable url)'
    }
}

/** Decode a bytea payload column into an object. Only vm_state may be gzip-compressed. */
export function decodeJsonBytea(
    buf: Buffer | null,
    { gzipTolerant = false }: { gzipTolerant?: boolean } = {}
): Record<string, any> | null {
    if (buf == null || buf.length === 0) {
        return null
    }
    let bytes = buf
    if (gzipTolerant && bytes.length >= 3 && GZIP_MAGIC.every((b, i) => bytes[i] === b)) {
        bytes = zlib.gunzipSync(bytes)
    }
    const text = bytes.toString('utf-8')
    if (text.length === 0) {
        return null
    }
    return parseJSON(text)
}

/**
 * Rebuild the in-memory `CyclotronJob` the V1 worker would have produced, then hand it to
 * the same `cyclotronJobToInvocation` the drain worker uses. This keeps the payload ->
 * invocation conversion identical to production rather than reinventing it.
 */
export function rowToInvocation(row: V1Row): CyclotronJobInvocation {
    const job: CyclotronJob = {
        id: row.id,
        teamId: row.team_id,
        functionId: row.function_id,
        created: new Date(),
        lockId: null,
        lastHeartbeat: null,
        janitorTouchCount: 0,
        transitionCount: 0,
        lastTransition: new Date(),
        queueName: row.queue_name,
        state: 'available',
        priority: row.priority,
        // cyclotronJobToInvocation expects an ISO string; preserve the original schedule.
        scheduled: row.scheduled ? row.scheduled.toISOString() : null,
        parentRunId: row.parent_run_id,
        vmState: decodeJsonBytea(row.vm_state, { gzipTolerant: true }),
        metadata: decodeJsonBytea(row.metadata),
        parameters: decodeJsonBytea(row.parameters),
        blob: row.blob ? new Uint8Array(row.blob) : null,
    }
    return cyclotronJobToInvocation(job)
}

/** Minimal CdpConfig slice CyclotronJobQueuePostgresV2 needs as a producer. */
export function buildV2Config(
    v2Url: string
): Pick<
    CdpConfig,
    | 'CYCLOTRON_NODE_DATABASE_URL'
    | 'CYCLOTRON_SHARD_DEPTH_LIMIT'
    | 'CDP_CYCLOTRON_BATCH_DELAY_MS'
    | 'CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE'
    | 'CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES'
    | 'CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS'
> {
    return {
        CYCLOTRON_NODE_DATABASE_URL: v2Url,
        CYCLOTRON_SHARD_DEPTH_LIMIT: 1_000_000,
        CDP_CYCLOTRON_BATCH_DELAY_MS: 50,
        CDP_CYCLOTRON_INSERT_MAX_BATCH_SIZE: 100,
        CDP_CYCLOTRON_INSERT_PARALLEL_BATCHES: false,
        CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS: '',
    }
}

async function fetchRows(v1: RelocateDeps['v1'], queue: string): Promise<V1Row[]> {
    const result = await v1.query<V1Row>(
        `SELECT id, team_id, function_id, queue_name, priority, parent_run_id,
                vm_state, metadata, parameters, blob, scheduled,
                scheduled::text AS scheduled_raw,
                (scheduled > now() + ${CORRUPT_CUTOFF_INTERVAL}) AS is_corrupt
         FROM cyclotron_jobs
         WHERE queue_name = $1 AND state = 'available'`,
        [queue]
    )
    return result.rows
}

/** Which of the given ids currently exist in V2. This is the delete gate. */
async function fetchExistingV2Ids(v2: RelocateDeps['v2Pool'], ids: string[]): Promise<Set<string>> {
    if (ids.length === 0) {
        return new Set()
    }
    const result = await v2.query<{ id: string }>(`SELECT id FROM cyclotron_jobs WHERE id = ANY($1::uuid[])`, [ids])
    return new Set(result.rows.map((r) => r.id))
}

/** Delete only rows still `available` on the target queue — never touch anything else. */
async function deleteFromV1(v1: RelocateDeps['v1'], ids: string[], queue: string): Promise<number> {
    if (ids.length === 0) {
        return 0
    }
    const result = await v1.query(
        `DELETE FROM cyclotron_jobs
         WHERE id = ANY($1::uuid[]) AND queue_name = $2 AND state = 'available'`,
        [ids, queue]
    )
    return result.rowCount ?? 0
}

async function countRemaining(v1: RelocateDeps['v1'], queue: string): Promise<number> {
    const result = await v1.query<{ count: string }>(
        `SELECT count(*) AS count FROM cyclotron_jobs WHERE queue_name = $1 AND state = 'available'`,
        [queue]
    )
    return parseInt(result.rows[0].count, 10)
}

function summarizeSchedule(rows: V1Row[]): string {
    if (rows.length === 0) {
        return 'none'
    }
    const raws = rows.map((r) => r.scheduled_raw ?? '(null)').sort()
    return `${raws[0]} .. ${raws[raws.length - 1]}`
}

function sampleIds(rows: V1Row[], n = 5): string {
    return rows
        .slice(0, n)
        .map((r) => r.id)
        .join(', ')
}

/**
 * Core orchestration, dependency-injected so it can be exercised end-to-end against real V1
 * and V2 databases (or fakes) without process wiring. See the safety/idempotency notes at
 * the top of the file — the write -> verify -> delete ordering lives here.
 */
export async function relocate(deps: RelocateDeps, args: RelocateArgs): Promise<RelocateResult> {
    const log = deps.log ?? (() => undefined)

    const rows = await fetchRows(deps.v1, args.queue)
    const legit = rows.filter((r) => !r.is_corrupt)
    const corrupt = rows.filter((r) => r.is_corrupt)

    log(`Found ${rows.length} available '${args.queue}' rows in V1:`)
    log(`  legit (relocate): ${legit.length}  scheduled: ${summarizeSchedule(legit)}`)
    log(`    sample ids: ${sampleIds(legit) || '(none)'}`)
    log(`  corrupt (delete): ${corrupt.length}  scheduled: ${summarizeSchedule(corrupt)}`)
    log(`    sample ids: ${sampleIds(corrupt) || '(none)'}`)

    if (!args.apply) {
        log(
            `DRY-RUN: would relocate ${legit.length} row(s) to V2 (preserving id + scheduled), ` +
                `then delete those verified ids from V1, and delete ${corrupt.length} corrupt row(s).`
        )
        return {
            legitCount: legit.length,
            corruptCount: corrupt.length,
            verifiedIds: [],
            missingIds: [],
            relocated: 0,
            deletedCorrupt: 0,
            remaining: rows.length,
            applied: false,
        }
    }

    await deps.v2Queue.startAsProducer()

    let verifiedIds: string[] = []
    let missingIds: string[] = []
    let relocated = 0

    if (legit.length > 0) {
        const invocations = legit.map(rowToInvocation)

        // (a) Write to V2. overwriteExisting upserts only over terminal rows; an id already
        // present in an active state throws CyclotronJobConflictError, which here means
        // "already relocated" — those still pass the verification gate below, so the conflict
        // is informational, not fatal. Any OTHER error propagates and aborts before any V1
        // delete, so V1 is never emptied ahead of a confirmed V2 write.
        try {
            await deps.v2Queue.queueInvocations(invocations, { overwriteExisting: true })
        } catch (e) {
            if (!(e instanceof CyclotronJobConflictError)) {
                throw e
            }
            const ids = Array.isArray(e.conflictingIds) ? e.conflictingIds : [e.conflictingIds]
            log(`Note: ${ids.length} id(s) already present in V2 (active) — will verify + drain from V1.`)
        }

        // (b) Verify every id is now present in V2 before deleting anything from V1.
        const legitIds = legit.map((r) => r.id)
        const presentInV2 = await fetchExistingV2Ids(deps.v2Pool, legitIds)
        verifiedIds = legitIds.filter((id) => presentInV2.has(id))
        missingIds = legitIds.filter((id) => !presentInV2.has(id))

        if (missingIds.length > 0) {
            log(`WARNING: ${missingIds.length} id(s) not confirmed in V2 — NOT deleting these from V1.`)
            log(`  sample missing: ${missingIds.slice(0, 5).join(', ')}`)
        }

        // (c) Only now delete the verified ids from V1.
        relocated = await deleteFromV1(deps.v1, verifiedIds, args.queue)
        log(`Relocated ${verifiedIds.length} id(s) to V2, deleted ${relocated} from V1.`)
    }

    // (d) Separately delete the corrupt rows — never relocated.
    const deletedCorrupt = await deleteFromV1(
        deps.v1,
        corrupt.map((r) => r.id),
        args.queue
    )

    const remaining = await countRemaining(deps.v1, args.queue)

    return {
        legitCount: legit.length,
        corruptCount: corrupt.length,
        verifiedIds,
        missingIds,
        relocated,
        deletedCorrupt,
        remaining,
        applied: true,
    }
}

async function main(): Promise<void> {
    const args = parseArgs(process.argv.slice(2))

    console.log('='.repeat(72))
    console.log(`cyclotron V1 -> V2 relocation  (queue=${args.queue}, env=${args.envLabel})`)
    console.log(`  V1 (source, will be emptied): ${describeUrl(args.v1Url)}`)
    console.log(`  V2 (target):                  ${describeUrl(args.v2Url)}`)
    console.log(`  mode: ${args.apply ? 'APPLY (will write + delete)' : 'DRY-RUN (no writes)'}`)
    console.log('='.repeat(72))

    const v1 = new Pool({ connectionString: args.v1Url, max: 4 })
    const v2Pool = new Pool({ connectionString: args.v2Url, max: 4 })
    const v2Queue = new CyclotronJobQueuePostgresV2(1, buildV2Config(args.v2Url))

    try {
        const result = await relocate({ v1, v2Pool, v2Queue, log: (m) => console.log(m) }, args)

        console.log('\n' + '='.repeat(72))
        if (!result.applied) {
            console.log('DRY-RUN complete. Re-run with --apply to execute.')
        } else {
            console.log('SUMMARY')
            console.log(`  relocated to V2:            ${result.relocated}`)
            console.log(`  deleted corrupt from V1:    ${result.deletedCorrupt}`)
            console.log(`  remaining V1 '${args.queue}' available rows: ${result.remaining} (expect 0)`)
            if (result.missingIds.length > 0) {
                console.log(`  NOT deleted (unconfirmed in V2): ${result.missingIds.length}`)
            }
        }
        console.log('='.repeat(72))
    } finally {
        await v2Queue.stopProducer().catch(() => undefined)
        await v1.end().catch(() => undefined)
        await v2Pool.end().catch(() => undefined)
    }
}

if (require.main === module) {
    main()
        .then(() => process.exit(0))
        .catch((e) => {
            console.error('\nrelocate-cyclotron-v1-jobs FAILED:', e)
            process.exit(1)
        })
}
