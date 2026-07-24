import { ClickHouseClient } from '@clickhouse/client'
import { randomUUID } from 'crypto'
import { Counter } from 'prom-client'

import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { logger } from '~/common/utils/logger'

import { ReputationMetrics, ReputationThresholds, classifyReputation } from './classifier'
import { BatchEvaluationSummary, HourlyEmailMetricsRow } from './types'

const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

const reputationSnapshotsCounter = new Counter({
    name: 'email_reputation_snapshots_total',
    help: 'Email reputation snapshot rows written by the evaluator',
    labelNames: ['scope', 'state'],
})

interface HogFlowRow {
    id: string
    team_id: number
}

export interface EmailReputationServiceConfig {
    /** Floor for each target's representative volume — small senders' windows stretch back
     * (up to the lookback) until at least this many sends are covered. */
    targetVolume: number
    /** ...and must span at least this many hours — so a high-volume sender is judged on at
     * least a full day of mail, not just the newest buckets that happen to reach the volume. */
    minWindowHours: number
    /** How far back to scan for that volume. Bounded by app_metrics2's 90-day TTL. */
    lookbackDays: number
    /** Scales each target's representative volume to its own sending scale:
     * volume = max(targetVolume, multiplier × its biggest sending day in the lookback).
     * This is what makes the window span multiple campaigns — see representativeVolume(). */
    representativeVolumeMultiplier: number
    thresholds: ReputationThresholds
}

interface SnapshotRow {
    teamId: number
    hogFlowId: string | null
    scope: 'workflow' | 'team'
    state: string
    bounceRate: number
    complaintRate: number
    emailsSent: number
}

/**
 * Computes per-workflow and per-team email sender reputation snapshots from app_metrics2.
 * Calculation only — no enforcement. Each daily run appends one snapshot row per target to
 * posthog_emailreputationsnapshot, so the table doubles as a time series for trend dashboards.
 *
 * Rates are volume-based, mirroring how AWS SES judges the shared sending account: each target's
 * bounce/complaint rate covers at least its most recent representative volume of sends AND at
 * least the last `minWindowHours` — whichever reaches further back (walking hourly buckets
 * backwards from the evaluation time, capped at `lookbackDays`). The representative volume is
 * sized to the target's own scale — `max(targetVolume, multiplier × its biggest sending day)` —
 * so the window always spans multiple typical campaigns: a weekly batch blast keeps counting
 * until enough newer batches dilute it (one clean batch can't wash it out), and a high-volume
 * sender can't bury a bad morning under a few clean recent hours. Because each window ends at
 * evaluation time, bounces that arrive hours after their send are picked up by the next run
 * automatically.
 *
 * Runs as Temporal activities: the workflow fetches the team list once, then evaluates teams in
 * paced batches. All rows of a run share the workflow's `evaluatedAt`, and inserts are
 * ON CONFLICT DO NOTHING against a unique (team, hog_flow, evaluated_at) index, so activity
 * retries are idempotent.
 */
export class EmailReputationService {
    constructor(
        private clickhouse: ClickHouseClient,
        private postgres: PostgresRouter,
        private config: EmailReputationServiceConfig
    ) {}

    /**
     * One page of teams to evaluate: those that sent workflow email within the lookback, plus
     * teams with a recent nonzero snapshot that have gone silent — the latter get an explicit
     * carry-forward snapshot so "latest reputation" never silently goes stale.
     *
     * Cursor-paginated by team id (activity results ride Temporal workflow history, so the full
     * fleet-wide id list must never be one payload): both sources are queried for ids >
     * `cursorTeamId` in id order, merged, and truncated to `pageSize`; `nextCursor` is null on
     * the last page.
     */
    public async fetchTeamsToEvaluate(
        evaluatedAt: string,
        cursorTeamId: number,
        pageSize: number
    ): Promise<{ teamIds: number[]; nextCursor: number | null }> {
        const result = await this.clickhouse.query({
            query: `
                SELECT DISTINCT team_id
                FROM app_metrics2
                WHERE app_source = 'hog_flow'
                    AND metric_kind = 'email'
                    AND metric_name = 'email_sent'
                    AND team_id > {cursorTeamId:UInt64}
                    AND timestamp >= parseDateTimeBestEffort({evaluatedAt:String}) - INTERVAL {lookbackDays:UInt32} DAY
                    AND timestamp < parseDateTimeBestEffort({evaluatedAt:String})
                ORDER BY team_id
                LIMIT {pageSize:UInt32}
            `,
            query_params: { evaluatedAt, cursorTeamId, pageSize, lookbackDays: this.config.lookbackDays },
            format: 'JSONEachRow',
        })
        const rows = await result.json<{ team_id: number | string }>()
        const teamIds = new Set(rows.map((row) => Number(row.team_id)))

        const recentlyEvaluated = await this.postgres.query<{ team_id: number }>(
            PostgresUse.COMMON_READ,
            `SELECT DISTINCT team_id FROM posthog_emailreputationsnapshot
             WHERE hog_flow_id IS NULL AND emails_sent > 0 AND team_id > $3
                 AND evaluated_at >= $1::timestamptz - make_interval(days => $2)
             ORDER BY team_id LIMIT $4`,
            [evaluatedAt, this.config.lookbackDays, cursorTeamId, pageSize],
            'emailReputationFetchRecentTeams'
        )
        for (const row of recentlyEvaluated.rows) {
            teamIds.add(Number(row.team_id))
        }

        // Both sources returned their first `pageSize` ids after the cursor, so the merged set's
        // first `pageSize` ids are complete — anything beyond belongs to a later page.
        const merged = [...teamIds].sort((a, b) => a - b)
        const page = merged.slice(0, pageSize)
        const hasMore =
            merged.length > pageSize || rows.length === pageSize || recentlyEvaluated.rows.length === pageSize
        return { teamIds: page, nextCursor: hasMore && page.length > 0 ? page[page.length - 1] : null }
    }

    /**
     * Evaluate one batch of teams: fetch their hourly metrics, attribute them to workflows,
     * accumulate each target's most recent sends up to the target volume, classify, and append
     * snapshot rows. Anchored on `evaluatedAt` so a retried batch reads the same buckets and
     * dedupes against rows it already wrote.
     */
    public async evaluateTeamBatch(teamIds: number[], evaluatedAt: string): Promise<BatchEvaluationSummary> {
        const summary: BatchEvaluationSummary = {
            teamsEvaluated: 0,
            workflowsEvaluated: 0,
            snapshotsWritten: 0,
        }
        if (teamIds.length === 0) {
            return summary
        }

        const rows = await this.fetchHourlyEmailMetrics(teamIds, evaluatedAt)
        const { flows, sourceToFlow } = await this.resolveSources([...new Set(rows.map((r) => r.appSourceId))])
        const snapshots: SnapshotRow[] = []
        const minWindowStart = Math.floor(Date.parse(evaluatedAt) / 1000) - this.config.minWindowHours * 3600

        // Per-workflow: fold each source's hourly buckets into its workflow, then take each
        // workflow's window (>= minWindowHours and >= its representative volume of sends).
        const workflowBuckets = new Map<string, Map<number, ReputationMetrics>>()
        for (const row of rows) {
            const flowId = sourceToFlow.get(row.appSourceId)
            if (!flowId) {
                continue
            }
            // Defense in depth: the flow lookups aren't team-filtered, so a cross-team
            // app_source_id would otherwise attribute one team's bounces to another team's
            // workflow snapshot. Mismatched rows still count toward their own team's aggregate.
            const flow = flows.get(flowId)
            if (!flow || flow.team_id !== row.teamId) {
                continue
            }
            addBucket(getOrCreate(workflowBuckets, flowId), row)
        }
        for (const [flowId, buckets] of workflowBuckets) {
            const flow = flows.get(flowId)
            if (!flow) {
                continue
            }
            const totals = accumulateRecentVolume(buckets, this.representativeVolume(buckets), minWindowStart)
            const { state, bounceRate, complaintRate } = classifyReputation(totals, this.config.thresholds)
            snapshots.push({
                teamId: flow.team_id,
                hogFlowId: flow.id,
                scope: 'workflow',
                state,
                bounceRate,
                complaintRate,
                emailsSent: totals.sent,
            })
            summary.workflowsEvaluated++
        }

        // Per-team: the aggregate takes its own most-recent-volume window over ALL the team's
        // email (including sources that no longer resolve to a workflow), independent of the
        // per-workflow windows — mirroring the account-level rate SES computes.
        const teamBuckets = new Map<number, Map<number, ReputationMetrics>>()
        for (const row of rows) {
            addBucket(getOrCreate(teamBuckets, row.teamId), row)
        }
        for (const teamId of teamIds) {
            const buckets = teamBuckets.get(teamId)
            // No activity in the lookback: carry-forward snapshot. The team only entered the plan
            // via a recent nonzero snapshot, so record an explicit "no recent volume" row rather
            // than leaving a stale rate presented as current.
            const totals = buckets
                ? accumulateRecentVolume(buckets, this.representativeVolume(buckets), minWindowStart)
                : { sent: 0, bounced: 0, complained: 0 }
            const { state, bounceRate, complaintRate } = classifyReputation(totals, this.config.thresholds)
            snapshots.push({
                teamId,
                hogFlowId: null,
                scope: 'team',
                state,
                bounceRate,
                complaintRate,
                emailsSent: totals.sent,
            })
            summary.teamsEvaluated++
        }

        for (const snapshot of snapshots) {
            const inserted = await this.insertSnapshot(snapshot, evaluatedAt)
            if (inserted) {
                summary.snapshotsWritten++
                reputationSnapshotsCounter.labels(snapshot.scope, snapshot.state).inc()
            }
        }

        logger.info('[EmailReputation] evaluated batch', {
            teams: summary.teamsEvaluated,
            workflows: summary.workflowsEvaluated,
            snapshotsWritten: summary.snapshotsWritten,
            evaluatedAt,
        })
        return summary
    }

    private async fetchHourlyEmailMetrics(teamIds: number[], evaluatedAt: string): Promise<HourlyEmailMetricsRow[]> {
        const result = await this.clickhouse.query({
            // email_blocked is how SES complaint events are recorded (see helpers/ses.ts), hence
            // the `complained` alias. email_bounced_hard counts only Permanent bounces, matching
            // AWS's account bounce rate (which excludes transient greylisting/mailbox-full
            // traffic). The metric is emitted from the same deploy that created the snapshot
            // table, so windows reaching back before that deploy undercount bounces until it has
            // volume-window depth — acceptable while the score is visibility-only. No HAVING sent > 0: buckets holding only late-arriving
            // bounces/complaints must still count toward the window they fall into.
            query: `
                SELECT
                    team_id,
                    app_source_id,
                    toUnixTimestamp(toStartOfHour(timestamp)) AS hour_bucket,
                    sumIf(count, metric_name = 'email_sent') AS sent,
                    sumIf(count, metric_name = 'email_bounced_hard') AS bounced,
                    sumIf(count, metric_name = 'email_blocked') AS complained
                FROM app_metrics2
                WHERE app_source = 'hog_flow'
                    AND metric_kind = 'email'
                    AND metric_name IN ('email_sent', 'email_bounced_hard', 'email_blocked')
                    AND team_id IN ({teamIds:Array(UInt64)})
                    AND timestamp >= parseDateTimeBestEffort({evaluatedAt:String}) - INTERVAL {lookbackDays:UInt32} DAY
                    AND timestamp < parseDateTimeBestEffort({evaluatedAt:String})
                GROUP BY team_id, app_source_id, hour_bucket
            `,
            query_params: { teamIds, evaluatedAt, lookbackDays: this.config.lookbackDays },
            format: 'JSONEachRow',
        })
        const rows = await result.json<{
            team_id: number | string
            app_source_id: string
            hour_bucket: number | string
            sent: number | string
            bounced: number | string
            complained: number | string
        }>()

        return rows.map((row) => ({
            teamId: Number(row.team_id),
            appSourceId: row.app_source_id,
            hourBucket: Number(row.hour_bucket),
            sent: Number(row.sent),
            bounced: Number(row.bounced),
            complained: Number(row.complained),
        }))
    }

    /**
     * Resolve app_source_ids to workflows. Batch-triggered runs record metrics under the batch-job
     * id (`parentRunId`), not the workflow id — and batch broadcasts are the highest-risk email
     * blasts — so unmatched ids are resolved through workflows_hogflowbatchjob and folded into the
     * parent workflow. Ids matching neither (deleted flows, plain hog functions) resolve to
     * nothing and only count toward the team aggregate.
     */
    private async resolveSources(rawSourceIds: string[]): Promise<{
        flows: Map<string, HogFlowRow>
        sourceToFlow: Map<string, string>
    }> {
        // app_source_id comes straight from ClickHouse; a single non-UUID value would abort the
        // whole batch on the uuid[] casts below and poison the run until the row ages out.
        // Non-UUID sources can't be a workflow or batch job anyway — they only count team-level.
        const sourceIds = rawSourceIds.filter((id) => UUID_REGEX.test(id))
        const flows = await this.fetchHogFlows(sourceIds)
        const sourceToFlow = new Map<string, string>()
        for (const id of sourceIds) {
            if (flows.has(id)) {
                sourceToFlow.set(id, id)
            }
        }

        const unmatched = sourceIds.filter((id) => !sourceToFlow.has(id))
        const batchJobToFlow = await this.fetchBatchJobFlowIds(unmatched)
        const extraFlowIds = [...new Set(batchJobToFlow.values())].filter((id) => !flows.has(id))
        for (const [id, flow] of await this.fetchHogFlows(extraFlowIds)) {
            flows.set(id, flow)
        }
        for (const [batchJobId, flowId] of batchJobToFlow) {
            if (flows.has(flowId)) {
                sourceToFlow.set(batchJobId, flowId)
            }
        }

        return { flows, sourceToFlow }
    }

    private async fetchBatchJobFlowIds(ids: string[]): Promise<Map<string, string>> {
        if (ids.length === 0) {
            return new Map()
        }
        const result = await this.postgres.query<{ id: string; hog_flow_id: string }>(
            PostgresUse.COMMON_READ,
            `SELECT id, hog_flow_id FROM workflows_hogflowbatchjob WHERE id = ANY($1)`,
            [ids],
            'emailReputationFetchBatchJobs'
        )
        return new Map(result.rows.map((row) => [row.id, row.hog_flow_id]))
    }

    private async fetchHogFlows(ids: string[]): Promise<Map<string, HogFlowRow>> {
        if (ids.length === 0) {
            return new Map()
        }
        const result = await this.postgres.query<HogFlowRow>(
            PostgresUse.COMMON_READ,
            `SELECT id, team_id FROM posthog_hogflow WHERE id = ANY($1)`,
            [ids],
            'emailReputationFetchHogFlows'
        )
        return new Map(result.rows.map((row) => [row.id, row]))
    }

    private representativeVolume(buckets: Map<number, ReputationMetrics>): number {
        return representativeVolume(buckets, this.config.targetVolume, this.config.representativeVolumeMultiplier)
    }

    /** Returns true if a row was written, false if it already existed (retry dedupe). */
    private async insertSnapshot(snapshot: SnapshotRow, evaluatedAt: string): Promise<boolean> {
        const result = await this.postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO posthog_emailreputationsnapshot
                (id, team_id, hog_flow_id, scope, state, bounce_rate, complaint_rate, emails_sent,
                 evaluated_at, created_at)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, now())
             ON CONFLICT DO NOTHING`,
            [
                randomUUID(),
                snapshot.teamId,
                snapshot.hogFlowId,
                snapshot.scope,
                snapshot.state,
                snapshot.bounceRate,
                snapshot.complaintRate,
                snapshot.emailsSent,
                evaluatedAt,
            ],
            'emailReputationInsertSnapshot'
        )
        return (result.rowCount ?? 0) > 0
    }
}

function getOrCreate<K>(map: Map<K, Map<number, ReputationMetrics>>, key: K): Map<number, ReputationMetrics> {
    let value = map.get(key)
    if (!value) {
        value = new Map()
        map.set(key, value)
    }
    return value
}

function addBucket(buckets: Map<number, ReputationMetrics>, row: HourlyEmailMetricsRow): void {
    const acc = buckets.get(row.hourBucket) ?? { sent: 0, bounced: 0, complained: 0 }
    acc.sent += row.sent
    acc.bounced += row.bounced
    acc.complained += row.complained
    buckets.set(row.hourBucket, acc)
}

/**
 * Sizes a target's representative volume from its own sending scale, mirroring AWS SES's stated
 * principle that rates are computed over "representative volume" sized to limit the influence of
 * any single campaign:
 *
 *     volume = max(floor, multiplier × biggest sending day in the buckets)
 *
 * Anchoring on the biggest single day (rather than an average) is what makes bursty senders
 * work: a weekly 10k batch sender averages ~1.4k/day — under one campaign — but their max day
 * is 10k, so their window spans their last `multiplier` batches. The guarantee this buys: no
 * single day can contribute more than 1/multiplier of the window, so one clean campaign can
 * never fully wash out yesterday's disaster, and redemption means sending `multiplier` clean
 * campaigns. Days are UTC calendar days, matching the daily evaluation cadence.
 */
export function representativeVolume(
    buckets: Map<number, ReputationMetrics>,
    floor: number,
    multiplier: number
): number {
    const sentByDay = new Map<number, number>()
    for (const [hour, bucket] of buckets) {
        const day = Math.floor(hour / 86400)
        sentByDay.set(day, (sentByDay.get(day) ?? 0) + bucket.sent)
    }
    const maxDaily = Math.max(0, ...sentByDay.values())
    return Math.max(floor, multiplier * maxDaily)
}

/**
 * Walk hourly buckets (keyed by epoch seconds) newest-first. Every bucket at or after
 * `minWindowStart` is included unconditionally — a high-volume sender is judged on at least that
 * span, so a bad morning can't hide behind a few clean recent hours. Older buckets are then
 * included until the target send volume is reached (the crossing bucket counts whole — hourly
 * granularity), which is what stretches the window for low-volume senders. Bounce-only buckets
 * are naturally included, which is how late-arriving bounces get counted.
 */
export function accumulateRecentVolume(
    buckets: Map<number, ReputationMetrics>,
    targetVolume: number,
    minWindowStart: number
): ReputationMetrics {
    const hours = [...buckets.keys()].sort((a, b) => b - a)
    const totals: ReputationMetrics = { sent: 0, bounced: 0, complained: 0 }
    for (const hour of hours) {
        if (hour < minWindowStart && totals.sent >= targetVolume) {
            break
        }
        const bucket = buckets.get(hour)!
        totals.sent += bucket.sent
        totals.bounced += bucket.bounced
        totals.complained += bucket.complained
    }
    return totals
}
