import { getRefreshScheduleLabel, getTableKindLabel } from './viewKind'

describe('viewKind', () => {
    describe('getTableKindLabel', () => {
        test.each([
            // The icon carries the kind of a saved view, so a text badge would only take space from the name.
            ['a plain saved view has no badge', { type: 'view', view: { is_materialized: false } }, null],
            ['a materialized saved view has no badge', { type: 'view', view: { is_materialized: true } }, null],
            ['a materialized view table has no badge', { type: 'table', table: { type: 'materialized_view' } }, null],
            ['a view nested under a table keeps its badge', { type: 'view-table', traversedFieldType: 'view' }, 'view'],
            [
                'a materialized view nested under a table keeps its badge',
                { type: 'view-table', traversedFieldType: 'materialized_view' },
                'materialized view',
            ],
            ['a managed view keeps its badge', { type: 'managed-view' }, 'managed view'],
            ['an endpoint keeps its badge', { type: 'endpoint' }, 'materialized endpoint'],
            ['a join keeps its badge', { type: 'lazy-table' }, 'join'],
            [
                'a batch export table keeps its badge',
                { type: 'table', table: { type: 'batch_export' } },
                'batch export',
            ],
            ['a PostHog table has no badge', { type: 'table', table: { type: 'posthog' } }, null],
            ['a row with no record has no badge', undefined, null],
        ])('%s', (_name, record, expected) => {
            expect(getTableKindLabel(record)).toEqual(expected)
        })
    })

    describe('getRefreshScheduleLabel', () => {
        test.each([
            ['names a known cadence', '6hour', 'Refreshes every 6 hours'],
            ['names a daily cadence', '24hour', 'Refreshes every 1 day'],
            ['says nothing when the view never refreshes', 'never', null],
            ['says nothing when the view has no frequency', undefined, null],
        ])('%s', (_name, syncFrequency, expected) => {
            expect(getRefreshScheduleLabel(syncFrequency)).toEqual(expected)
        })
    })
})
