import { randomUUID } from 'crypto'

import { FixtureHogFlowBuilder } from '~/cdp/_tests/builders/hogflow.builder'
import { insertHogFlow } from '~/cdp/_tests/fixtures-hogflows'
import { HogFlow } from '~/cdp/schema/hogflow'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { createTeam, getTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub } from '~/types'

import { DEFAULT_THRESHOLDS } from './classifier'
import { EmailReputationService } from './email-reputation.service'
import { HourlyEmailMetricsRow } from './types'

const EVALUATED_AT = '2026-07-10T06:00:00.000Z'
const HOURS_AGO = (hours: number): number => Math.floor(Date.parse(EVALUATED_AT) / 1000) - hours * 3600

describe('EmailReputationService', () => {
    jest.setTimeout(5000)

    let hub: Hub
    let service: EmailReputationService
    let mockClickhouse: { query: jest.Mock }
    let teamId: number

    const insertEmailFlow = async (): Promise<HogFlow> => {
        return await insertHogFlow(
            hub.postgres,
            new FixtureHogFlowBuilder()
                .withTeamId(teamId)
                .withStatus('active')
                .withWorkflow({
                    actions: {
                        trigger: { type: 'trigger', config: { type: 'event', filters: {} } },
                        send_email: { type: 'function_email', config: { template_id: 'template-email' } } as any,
                        exit: { type: 'exit', config: {} },
                    },
                    edges: [
                        { from: 'trigger', to: 'send_email', type: 'continue' },
                        { from: 'send_email', to: 'exit', type: 'continue' },
                    ],
                })
                .build()
        )
    }

    const insertBatchJob = async (hogFlowId: string): Promise<string> => {
        const batchJobId = randomUUID()
        await hub.postgres.query(
            PostgresUse.COMMON_WRITE,
            `INSERT INTO workflows_hogflowbatchjob (id, team_id, hog_flow_id, variables, filters, status, created_at, updated_at)
             VALUES ($1, $2, $3, '{}', '{}', 'completed', now(), now())`,
            [batchJobId, teamId, hogFlowId],
            'testInsertBatchJob'
        )
        return batchJobId
    }

    const mockMetrics = (rows: HourlyEmailMetricsRow[]): void => {
        mockClickhouse.query.mockResolvedValue({
            json: () =>
                Promise.resolve(
                    rows.map((row) => ({
                        team_id: row.teamId,
                        app_source_id: row.appSourceId,
                        hour_bucket: row.hourBucket,
                        sent: row.sent,
                        bounced: row.bounced,
                        complained: row.complained,
                    }))
                ),
        })
    }

    const getSnapshots = async (): Promise<any[]> => {
        const result = await hub.postgres.query(
            PostgresUse.COMMON_READ,
            `SELECT * FROM posthog_emailreputationsnapshot WHERE team_id = $1 ORDER BY scope, hog_flow_id, evaluated_at`,
            [teamId],
            'testGetSnapshots'
        )
        return result.rows
    }

    beforeEach(async () => {
        hub = await createHub()
        await resetTestDatabase()
        const team = await getTeam(hub.postgres, 2)
        teamId = await createTeam(hub.postgres, team!.organization_id)
        mockClickhouse = { query: jest.fn() }
        service = new EmailReputationService(mockClickhouse as any, hub.postgres, {
            targetVolume: 1000,
            minWindowHours: 24,
            lookbackDays: 30,
            thresholds: DEFAULT_THRESHOLDS,
        })
    })

    afterEach(async () => {
        await closeHub(hub)
    })

    it('writes workflow and team snapshots, and a retried batch adds no duplicate rows', async () => {
        const flow = await insertEmailFlow()
        mockMetrics([
            { teamId, appSourceId: flow.id, hourBucket: HOURS_AGO(2), sent: 1000, bounced: 60, complained: 0 },
        ])

        const summary = await service.evaluateTeamBatch([teamId], EVALUATED_AT)
        expect(summary).toMatchObject({ teamsEvaluated: 1, workflowsEvaluated: 1, snapshotsWritten: 2 })

        const rows = await getSnapshots()
        expect(rows).toHaveLength(2)
        const workflowRow = rows.find((r) => r.hog_flow_id === flow.id)
        expect(workflowRow).toMatchObject({ scope: 'workflow', state: 'critical', emails_sent: '1000' })
        expect(workflowRow.bounce_rate).toBeCloseTo(0.06)
        expect(rows.find((r) => r.hog_flow_id === null)).toMatchObject({ scope: 'team', state: 'critical' })

        // Same evaluatedAt (a Temporal activity retry) dedupes on the unique index
        const retry = await service.evaluateTeamBatch([teamId], EVALUATED_AT)
        expect(retry.snapshotsWritten).toEqual(0)
        expect(await getSnapshots()).toHaveLength(2)

        // A later run appends new history rows instead of updating in place
        await service.evaluateTeamBatch([teamId], '2026-07-11T06:00:00.000Z')
        expect(await getSnapshots()).toHaveLength(4)
    })

    it('computes rates over the most recent target volume, keeping an old batch until newer sends displace it', async () => {
        const flow = await insertEmailFlow()
        // A 5%-bounce batch 6 days ago and only 400 newer clean sends: the window (target 1000)
        // still reaches back to the batch, so it keeps counting — no fixed-24h cliff.
        mockMetrics([
            { teamId, appSourceId: flow.id, hourBucket: HOURS_AGO(144), sent: 1000, bounced: 50, complained: 0 },
            { teamId, appSourceId: flow.id, hourBucket: HOURS_AGO(2), sent: 400, bounced: 0, complained: 0 },
        ])
        await service.evaluateTeamBatch([teamId], EVALUATED_AT)

        let workflowRow = (await getSnapshots()).find((r) => r.hog_flow_id === flow.id)
        // 1400 sent / 50 bounced ≈ 3.6% → warning (diluted below the 5% critical line but still counted)
        expect(workflowRow).toMatchObject({ state: 'warning', emails_sent: '1400' })
        expect(workflowRow.bounce_rate).toBeCloseTo(50 / 1400)

        // Once newer volume alone reaches the target, the old batch falls out of the window
        mockMetrics([
            { teamId, appSourceId: flow.id, hourBucket: HOURS_AGO(144), sent: 1000, bounced: 50, complained: 0 },
            { teamId, appSourceId: flow.id, hourBucket: HOURS_AGO(2), sent: 1000, bounced: 5, complained: 0 },
        ])
        await service.evaluateTeamBatch([teamId], '2026-07-11T06:00:00.000Z')

        const laterRows = await getSnapshots()
        workflowRow = laterRows.filter((r) => r.hog_flow_id === flow.id).at(-1)
        expect(workflowRow).toMatchObject({ state: 'healthy', emails_sent: '1000' })
        expect(workflowRow.bounce_rate).toBeCloseTo(0.005)
    })

    it('judges a high-volume sender on at least the minimum window, not just the newest buckets', async () => {
        const flow = await insertEmailFlow()
        // The newest bucket alone exceeds the 1000-send target and is clean; the bad blast 20h
        // earlier is inside the 24h floor and must still count — stopping at the volume target
        // would report this sender healthy while the shared account absorbed 10% bounces.
        mockMetrics([
            { teamId, appSourceId: flow.id, hourBucket: HOURS_AGO(2), sent: 5000, bounced: 0, complained: 0 },
            { teamId, appSourceId: flow.id, hourBucket: HOURS_AGO(20), sent: 5000, bounced: 500, complained: 0 },
        ])

        await service.evaluateTeamBatch([teamId], EVALUATED_AT)

        const workflowRow = (await getSnapshots()).find((r) => r.hog_flow_id === flow.id)
        // 10000 sent / 500 bounced = 5% → critical
        expect(workflowRow).toMatchObject({ state: 'critical', emails_sent: '10000' })
        expect(workflowRow.bounce_rate).toBeCloseTo(0.05)
    })

    it('counts late-arriving bounces from bounce-only buckets newer than the sends', async () => {
        const flow = await insertEmailFlow()
        mockMetrics([
            { teamId, appSourceId: flow.id, hourBucket: HOURS_AGO(10), sent: 1000, bounced: 10, complained: 0 },
            // Bounces that arrived hours after the send, in a bucket with zero sends
            { teamId, appSourceId: flow.id, hourBucket: HOURS_AGO(3), sent: 0, bounced: 45, complained: 0 },
        ])

        await service.evaluateTeamBatch([teamId], EVALUATED_AT)

        const workflowRow = (await getSnapshots()).find((r) => r.hog_flow_id === flow.id)
        // 55/1000 = 5.5% → critical; dropping the bounce-only bucket would misreport 1% healthy
        expect(workflowRow).toMatchObject({ state: 'critical' })
        expect(workflowRow.bounce_rate).toBeCloseTo(0.055)
    })

    it('folds batch-job metrics into the parent workflow and counts orphans only at team level', async () => {
        const flow = await insertEmailFlow()
        const batchJobId = await insertBatchJob(flow.id)
        mockMetrics([
            { teamId, appSourceId: flow.id, hourBucket: HOURS_AGO(4), sent: 400, bounced: 4, complained: 0 },
            { teamId, appSourceId: batchJobId, hourBucket: HOURS_AGO(3), sent: 600, bounced: 20, complained: 0 },
            // Matches neither a flow nor a batch job (e.g. deleted flow): team aggregate only
            { teamId, appSourceId: randomUUID(), hourBucket: HOURS_AGO(2), sent: 100, bounced: 100, complained: 0 },
            // Cross-team app_source_id (another team's metrics naming our flow): must not touch
            // our workflow snapshot, and counts only toward the foreign team's aggregate
            {
                teamId: teamId + 1,
                appSourceId: flow.id,
                hourBucket: HOURS_AGO(2),
                sent: 500,
                bounced: 250,
                complained: 0,
            },
        ])

        await service.evaluateTeamBatch([teamId], EVALUATED_AT)

        const rows = await getSnapshots()
        const workflowRow = rows.find((r) => r.hog_flow_id === flow.id)
        // 400+600 sent, 4+20 bounced = 2.4% → warning
        expect(workflowRow).toMatchObject({ state: 'warning', emails_sent: '1000' })
        expect(workflowRow.bounce_rate).toBeCloseTo(0.024)

        const teamRow = rows.find((r) => r.hog_flow_id === null)
        // Orphan row included: 1100 sent, 124 bounced ≈ 11.3% → critical
        expect(teamRow).toMatchObject({ state: 'critical', emails_sent: '1100' })
    })

    it('pools the tenant rate across workflows instead of averaging or escalating per-workflow states', async () => {
        const bigFlow = await insertEmailFlow()
        const toxicFlow = await insertEmailFlow()
        mockMetrics([
            { teamId, appSourceId: bigFlow.id, hourBucket: HOURS_AGO(4), sent: 50000, bounced: 150, complained: 0 },
            { teamId, appSourceId: toxicFlow.id, hourBucket: HOURS_AGO(3), sent: 2000, bounced: 160, complained: 0 },
        ])

        await service.evaluateTeamBatch([teamId], EVALUATED_AT)

        const rows = await getSnapshots()
        // Per workflow: each judged on its own stream
        expect(rows.find((r) => r.hog_flow_id === bigFlow.id)).toMatchObject({ state: 'healthy' })
        expect(rows.find((r) => r.hog_flow_id === toxicFlow.id)).toMatchObject({ state: 'critical' })

        // Tenant: pooled bounces / pooled sends (what SES's account ledger sees) ≈ 0.6% → healthy.
        // Escalating to the worst workflow state would say critical; averaging the two rates
        // (~4.2%) would say warning — both are wrong.
        const teamRow = rows.find((r) => r.hog_flow_id === null)
        expect(teamRow).toMatchObject({ state: 'healthy', emails_sent: '52000' })
        expect(teamRow.bounce_rate).toBeCloseTo(310 / 52000)
    })

    it('writes a carry-forward team snapshot when a recently evaluated team goes silent', async () => {
        const flow = await insertEmailFlow()
        mockMetrics([
            { teamId, appSourceId: flow.id, hourBucket: HOURS_AGO(2), sent: 1000, bounced: 60, complained: 0 },
        ])
        await service.evaluateTeamBatch([teamId], EVALUATED_AT)

        // Next run: no sends at all — the team still enters the plan via its recent snapshot...
        mockMetrics([])
        const nextRun = '2026-07-11T06:00:00.000Z'
        const plan = await service.fetchTeamsToEvaluate(nextRun, 0, 5000)
        expect(plan.teamIds).toContain(teamId)

        // ...and gets an explicit zero-volume row instead of yesterday's critical staying "current"
        await service.evaluateTeamBatch([teamId], nextRun)
        const teamRows = (await getSnapshots()).filter((r) => r.hog_flow_id === null)
        expect(teamRows.at(-1)).toMatchObject({ state: 'insufficient_data', emails_sent: '0' })
    })
})
