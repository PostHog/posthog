import type { Pool } from 'pg'
import { z } from 'zod'

import { SCHEMA_VERSION } from '../scorecard/scorecard'

export const RunId = z.uuid().transform((runId) => runId.toLowerCase())

export const Scorecard = z
    .object({
        schema_version: z.literal(SCHEMA_VERSION),
        run_id: RunId,
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
    host: z.string().min(1).nullish(),
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
    evidenceDir: string | null
    receivedAt: string
    updatedAt: string
    scorecard: Record<string, unknown>
}

export type Run = RunSummary & { series: unknown; topology: unknown }

export type ListOptions = { cardId?: string; limit: number }

const isoText = (column: string): string =>
    `to_char(${column} AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS "${camelCase(column)}"`

function camelCase(column: string): string {
    return column.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase())
}

const SUMMARY_COLUMNS = [
    ...['run_id', 'card_id', 'status', 'target', 'host', 'head_sha', 'card_hash', 'evidence_dir'].map(
        (column) => `${column} AS "${camelCase(column)}"`
    ),
    ...['started_at', 'ended_at', 'received_at', 'updated_at'].map(isoText),
    'scorecard',
].join(', ')

const jsonOrNull = (value: unknown): string | null => (value == null ? null : JSON.stringify(value))

export class RunStore {
    constructor(private readonly pool: Pool) {}

    async put({ scorecard, series, topology, host }: RunReport): Promise<'created' | 'updated'> {
        const { rows } = await this.pool.query<{ created: boolean }>(
            `INSERT INTO runs (run_id, card_id, status, target, host, head_sha, card_hash, started_at, ended_at,
                               scorecard, series, topology, evidence_dir)
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
                evidence_dir = EXCLUDED.evidence_dir,
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
                jsonOrNull(series),
                jsonOrNull(topology),
                scorecard.evidence_dir ?? null,
            ]
        )
        return rows[0].created ? 'created' : 'updated'
    }

    async list({ cardId, limit }: ListOptions): Promise<RunSummary[]> {
        const { rows } = await this.pool.query<RunSummary>(
            `SELECT ${SUMMARY_COLUMNS} FROM runs
             WHERE $1::text IS NULL OR card_id = $1
             ORDER BY started_at DESC, run_id
             LIMIT $2`,
            [cardId ?? null, limit]
        )
        return rows
    }

    async get(runId: string): Promise<Run | undefined> {
        const { rows } = await this.pool.query<Run>(
            `SELECT ${SUMMARY_COLUMNS}, series, topology FROM runs WHERE run_id = $1`,
            [runId]
        )
        return rows[0]
    }
}
