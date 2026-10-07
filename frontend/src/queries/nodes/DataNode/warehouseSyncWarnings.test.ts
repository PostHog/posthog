import { DataWarehouseSyncWarning } from '~/queries/schema/schema-general'
import { DashboardTile, InsightModel, InsightShortId } from '~/types'

import { trimRedundantTail, warehouseSyncDashboardSummary } from './warehouseSyncWarnings'

function syncWarning(table: string): DataWarehouseSyncWarning {
    return {
        type: 'warehouse_sync',
        message: `Last sync of \`${table}\` (from Stripe) failed.`,
        schema_name: table,
        source_id: 'source-1',
        source_type: 'Stripe',
        status: 'Failed',
        table_name: `stripe_${table}`,
    }
}

function tile(id: number, insight: Partial<InsightModel> | null): DashboardTile {
    return { id, color: null, insight: insight ? (insight as InsightModel) : undefined }
}

describe('warehouseSyncWarnings', () => {
    describe('trimRedundantTail', () => {
        // Messages mirror those emitted by products/data_warehouse/backend/sync_status.py.
        test.each([
            [
                'stale completed sync drops the redundant tail',
                '`postgres_posthog_team` (from Postgres) last synced 2 hours ago, more than twice its configured sync interval. Results may be out of date.',
                '`postgres_posthog_team` (from Postgres) last synced 2 hours ago, more than twice its configured sync interval.',
            ],
            [
                'running sync keeps the in-progress note but drops the redundant tail',
                '`postgres_posthog_team` (from Postgres) last completed syncing 2 hours ago, more than twice its configured sync interval. A new sync is in progress but results may be out of date.',
                '`postgres_posthog_team` (from Postgres) last completed syncing 2 hours ago, more than twice its configured sync interval. A new sync is in progress.',
            ],
            [
                'billing limit reached drops the redundant tail',
                'Sync of `t` (from Stripe) is paused because the data warehouse billing limit has been reached. Results may be out of date.',
                'Sync of `t` (from Stripe) is paused because the data warehouse billing limit has been reached.',
            ],
            [
                'billing limit too low drops the redundant tail',
                'Sync of `t` (from Stripe) is paused because the configured billing limit is too low. Results may be out of date.',
                'Sync of `t` (from Stripe) is paused because the configured billing limit is too low.',
            ],
            [
                'paused message without the tail is left unchanged',
                'Sync of `t` (from Stripe) is paused. Results reflect the last successful sync from 2 hours ago.',
                'Sync of `t` (from Stripe) is paused. Results reflect the last successful sync from 2 hours ago.',
            ],
            [
                'failed message without the tail is left unchanged',
                'Last sync of `t` (from Stripe) failed. Results reflect data from 2 hours ago. Check the data warehouse source for details.',
                'Last sync of `t` (from Stripe) failed. Results reflect data from 2 hours ago. Check the data warehouse source for details.',
            ],
        ])('%s', (_name, input, expected) => {
            expect(trimRedundantTail(input)).toEqual(expected)
        })
    })

    it('summarizes the out-of-date sources behind a dashboard and the insights they affect', () => {
        const invoices = syncWarning('invoices')
        const leads: DataWarehouseSyncWarning = {
            ...syncWarning('leads'),
            source_id: 'source-2',
            source_type: 'Hubspot',
        }
        const tiles = [
            tile(1, { short_id: 'aaa' as InsightShortId, name: 'Revenue', warnings: [invoices] }),
            tile(2, { short_id: 'bbb' as InsightShortId, name: 'Pipeline', warnings: [invoices, leads] }),
            tile(3, { short_id: 'ccc' as InsightShortId, name: 'Healthy', warnings: null }),
            tile(4, { short_id: 'ddd' as InsightShortId, name: 'Deleted', warnings: [leads], deleted: true }),
            tile(5, {
                short_id: 'eee' as InsightShortId,
                name: 'Restricted',
                warnings: [{ type: 'access_control', message: 'Some objects are hidden.', resources: ['insight'] }],
            }),
            tile(6, null),
        ]

        const summary = warehouseSyncDashboardSummary(tiles)

        expect(summary?.sources).toEqual([
            { sourceType: 'Stripe', sourceId: 'source-1' },
            { sourceType: 'Hubspot', sourceId: 'source-2' },
        ])
        expect(summary?.insightCount).toEqual(2)
        expect(warehouseSyncDashboardSummary([tiles[2], tiles[4], tiles[5]])).toBeNull()
    })

    it('keeps the fingerprint when only the message age changes, and changes it when another table goes out of date', () => {
        const invoices = syncWarning('invoices')
        const fingerprint = (warnings: DataWarehouseSyncWarning[]): string | undefined =>
            warehouseSyncDashboardSummary([tile(1, { short_id: 'aaa' as InsightShortId, warnings })])?.fingerprint

        expect(fingerprint([{ ...invoices, message: 'Last sync of `invoices` failed a day ago.' }])).toEqual(
            fingerprint([invoices])
        )
        expect(fingerprint([invoices, syncWarning('charges')])).not.toEqual(fingerprint([invoices]))
    })
})
