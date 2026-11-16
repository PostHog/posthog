import type { Pool } from 'pg'
import { promisify } from 'util'
import { gunzip, gzip } from 'zlib'
import { z } from 'zod'

import { parseJSON } from '~/common/utils/json-parse'

const gzipAsync = promisify(gzip)
const gunzipAsync = promisify(gunzip)

// The store reads only the fields every scorecard carries; the rest is kept as posted.
export const Scorecard = z
    .object({
        schema_version: z.number().int(),
        run_id: z.uuid(),
        card_id: z.string().min(1),
        status: z.enum(['passed', 'failed', 'invalid']),
        started_at: z.iso.datetime(),
        ended_at: z.iso.datetime(),
        target: z.string().nullish(),
        head_sha: z.string().nullish(),
        card_hash: z.string().nullish(),
        evidence_dir: z.string().nullish(),
    })
    .catchall(z.unknown())

export const RunReport = z.object({
    scorecard: Scorecard,
    series: z.unknown().optional(),
    topology: z.unknown().optional(),
    host: z.string().min(1).optional(),
})

export type RunReport = z.infer<typeof RunReport>

export type RunSummary = {
    runId: string
    cardId: string
    status: string
    target: string | null
    host: string | null
    headSha: string | null
    cardHash: string | null
    startedAt: string
    endedAt: string
    evidencePrefix: string | null
    receivedAt: string
    updatedAt: string
    scorecard: Record<string, unknown>
}

export type Run = RunSummary & { series: unknown; topology: unknown }

export type ListOptions = { cardId?: string; limit: number }

type Row = {
    run_id: string
    card_id: string
    status: string
    target: string | null
    host: string | null
    head_sha: string | null
    card_hash: string | null
    started_at: Date | string
    ended_at: Date | string
    evidence_prefix: string | null
    received_at: Date | string
    updated_at: Date | string
    scorecard: Record<string, unknown>
}

const SUMMARY_COLUMNS =
    'run_id, card_id, status, target, host, head_sha, card_hash, started_at, ended_at, evidence_prefix, received_at, updated_at, scorecard'

// `src/common/utils/db/postgres.ts` makes pg parse timestamptz to a string for the whole process once it is
// imported, and the store also runs in processes that do not import it, so a row can carry either type.
const isoOf = (value: Date | string): string => new Date(value).toISOString()

function summaryOf(row: Row): RunSummary {
    return {
        runId: row.run_id,
        cardId: row.card_id,
        status: row.status,
        target: row.target,
        host: row.host,
        headSha: row.head_sha,
        cardHash: row.card_hash,
        startedAt: isoOf(row.started_at),
        endedAt: isoOf(row.ended_at),
        evidencePrefix: row.evidence_prefix,
        receivedAt: isoOf(row.received_at),
        updatedAt: isoOf(row.updated_at),
        scorecard: row.scorecard,
    }
}

export class RunStore {
    constructor(private readonly pool: Pool) {}

    // A report without series or topology keeps what an earlier report stored, so re-sending a
    // scorecard never drops the series a backfill added.
    async put({ scorecard, series, topology, host }: RunReport): Promise<'created' | 'updated'> {
        const packed = series === undefined ? null : await gzipAsync(JSON.stringify(series))
        const { rows } = await this.pool.query<{ created: boolean }>(
            `INSERT INTO runs (run_id, card_id, status, target, host, head_sha, card_hash, started_at, ended_at,
                               scorecard, series, topology, evidence_prefix)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
             ON CONFLICT (run_id) DO UPDATE SET
                card_id = EXCLUDED.card_id,
                status = EXCLUDED.status,
                target = EXCLUDED.target,
                host = COALESCE(EXCLUDED.host, runs.host),
                head_sha = EXCLUDED.head_sha,
                card_hash = EXCLUDED.card_hash,
                started_at = EXCLUDED.started_at,
                ended_at = EXCLUDED.ended_at,
                scorecard = EXCLUDED.scorecard,
                series = COALESCE(EXCLUDED.series, runs.series),
                topology = COALESCE(EXCLUDED.topology, runs.topology),
                evidence_prefix = EXCLUDED.evidence_prefix,
                updated_at = now()
             RETURNING (xmax = 0) AS created`,
            [
                scorecard.run_id,
                scorecard.card_id,
                scorecard.status,
                scorecard.target ?? null,
                host ?? null,
                scorecard.head_sha ?? null,
                scorecard.card_hash ?? null,
                scorecard.started_at,
                scorecard.ended_at,
                JSON.stringify(scorecard),
                packed,
                topology === undefined ? null : JSON.stringify(topology),
                scorecard.evidence_dir ?? null,
            ]
        )
        return rows[0].created ? 'created' : 'updated'
    }

    async list({ cardId, limit }: ListOptions): Promise<RunSummary[]> {
        const { rows } = await this.pool.query<Row>(
            `SELECT ${SUMMARY_COLUMNS} FROM runs
             WHERE $1::text IS NULL OR card_id = $1
             ORDER BY started_at DESC, run_id
             LIMIT $2`,
            [cardId ?? null, limit]
        )
        return rows.map(summaryOf)
    }

    async get(runId: string): Promise<Run | undefined> {
        const { rows } = await this.pool.query<Row & { series: Buffer | null; topology: unknown }>(
            `SELECT ${SUMMARY_COLUMNS}, series, topology FROM runs WHERE run_id = $1`,
            [runId]
        )
        if (rows.length === 0) {
            return undefined
        }
        const [row] = rows
        const series = row.series === null ? null : parseJSON((await gunzipAsync(row.series)).toString('utf8'))
        return { ...summaryOf(row), series, topology: row.topology }
    }
}
