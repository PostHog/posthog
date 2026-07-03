import { trimRedundantTail } from './syncWarnings'

describe('syncWarnings', () => {
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
})
