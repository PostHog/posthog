import type { Pool } from 'pg'
import { z } from 'zod'

export const RunId = z.uuid().transform((runId) => runId.toLowerCase())

const Name = z.string().min(1)

const Scorecard = z
    .object({
        schema_version: z.literal([1, 2]),
        run_id: RunId,
        card_id: Name,
        status: z.enum(['passed', 'failed', 'invalid']),
        started_at: z.iso.datetime(),
        ended_at: z.iso.datetime(),
        target: z.string().nullish(),
        head_sha: z.string().nullish(),
        card_hash: z.string().nullish(),
        evidence_dir: z.string().nullish(),
        adapters: z.array(Name).nullish(),
        owners: z.array(Name).nullish(),
    })
    .catchall(z.unknown())

const NamedSeries = z.object({
    adapter: Name,
    name: Name,
    unit: Name,
    labels: z.record(z.string(), z.string()).default({}),
    points: z.array(z.object({ at: z.number(), value: z.number().nullable() })),
})

export const RunReport = z.object({
    scorecard: Scorecard,
    series: z.array(NamedSeries).nullish(),
    topology: z.unknown().optional(),
    manifest: z.unknown().optional(),
    host: Name.nullish(),
})

export type RunReport = z.infer<typeof RunReport>

type RunSummary = {
    runId: string
    cardId: string
    status: string
    adapters: string[]
    owners: string[]
    target: string | null
    host: string | null
    headSha: string | null
    cardHash: string | null
    startedAt: string
    endedAt: string
    evidenceDir: string | null
    receivedAt: string
    updatedAt: string
}

export type Run = RunSummary & {
    scorecard: Record<string, unknown>
    series: z.infer<typeof NamedSeries>[] | null
    topology: unknown
    manifest: unknown
}

const SUMMARY_COLUMNS = `
    run_id AS "runId",
    card_id AS "cardId",
    status,
    adapters,
    owners,
    target,
    host,
    head_sha AS "headSha",
    card_hash AS "cardHash",
    to_char(started_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS "startedAt",
    to_char(ended_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS "endedAt",
    evidence_dir AS "evidenceDir",
    to_char(received_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS "receivedAt",
    to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"') AS "updatedAt"`

const jsonOrNull = (value: unknown): string | null => (value == null ? null : JSON.stringify(value))

export class RunStore {
    constructor(private readonly pool: Pool) {}

    async put({ scorecard, series, topology, manifest, host }: RunReport): Promise<'created' | 'updated'> {
        const { rows } = await this.pool.query<{ created: boolean }>(
            `INSERT INTO runs (run_id, card_id, status, adapters, owners, target, host, head_sha, card_hash,
                               started_at, ended_at, scorecard, series, topology, manifest, evidence_dir)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
             ON CONFLICT (run_id) DO UPDATE SET
                card_id = EXCLUDED.card_id,
                status = EXCLUDED.status,
                adapters = EXCLUDED.adapters,
                owners = EXCLUDED.owners,
                target = EXCLUDED.target,
                host = COALESCE(EXCLUDED.host, runs.host),
                head_sha = EXCLUDED.head_sha,
                card_hash = EXCLUDED.card_hash,
                started_at = EXCLUDED.started_at,
                ended_at = EXCLUDED.ended_at,
                scorecard = EXCLUDED.scorecard,
                series = COALESCE(EXCLUDED.series, runs.series),
                topology = COALESCE(EXCLUDED.topology, runs.topology),
                manifest = COALESCE(EXCLUDED.manifest, runs.manifest),
                evidence_dir = EXCLUDED.evidence_dir,
                updated_at = now()
             RETURNING (xmax = 0) AS created`,
            [
                scorecard.run_id,
                scorecard.card_id,
                scorecard.status,
                scorecard.adapters ?? [],
                scorecard.owners ?? [],
                scorecard.target ?? null,
                host ?? null,
                scorecard.head_sha ?? null,
                scorecard.card_hash ?? null,
                scorecard.started_at,
                scorecard.ended_at,
                JSON.stringify(scorecard),
                jsonOrNull(series),
                jsonOrNull(topology),
                jsonOrNull(manifest),
                scorecard.evidence_dir ?? null,
            ]
        )
        return rows[0].created ? 'created' : 'updated'
    }

    async list({
        cardId,
        adapter,
        limit,
    }: {
        cardId?: string
        adapter?: string
        limit: number
    }): Promise<RunSummary[]> {
        const { rows } = await this.pool.query<RunSummary>(
            `SELECT ${SUMMARY_COLUMNS} FROM runs
             WHERE ($1::text IS NULL OR card_id = $1)
               AND ($2::text IS NULL OR adapters @> ARRAY[$2::text])
             ORDER BY started_at DESC, run_id
             LIMIT $3`,
            [cardId ?? null, adapter ?? null, limit]
        )
        return rows
    }

    async get(runId: string): Promise<Run | undefined> {
        const { rows } = await this.pool.query<Run>(
            `SELECT ${SUMMARY_COLUMNS}, scorecard, series, topology, manifest FROM runs WHERE run_id = $1`,
            [runId]
        )
        return rows[0]
    }
}
