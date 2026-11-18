import { dayjs } from 'lib/dayjs'

import { byStatusAttention, checkRunDisplayName, failingForLabel, runResultCell } from './checksConstants'
import { CheckTypeEnumApi } from './generated/api.schemas'

describe('checksConstants', () => {
    const now = dayjs('2026-08-19T12:00:00Z')

    // A red tag alone never says "since when", and the answer can be older than any page of run
    // history, so it has to come off the check rather than be derived from the runs on screen.
    it.each<[string, string, string | null, string | null, string | null]>([
        ['passing checks say nothing', 'passed', '2026-08-19T11:00:00Z', null, null],
        ['checks that never ran say nothing', '', null, null, null],
        [
            'a failing check counts from when it started failing, not from its last pass',
            'failed',
            '2026-08-16T12:00:00Z',
            '2026-08-19T11:55:00Z',
            'for 5 minutes',
        ],
        ['an erroring check counts too', 'errored', null, '2026-08-19T09:00:00Z', 'for 3 hours'],
        ['a check with no pass on record says so', 'failed', null, null, 'never passed'],
        [
            'a check failing since before the streak was tracked says nothing',
            'failed',
            '2026-08-16T12:00:00Z',
            null,
            null,
        ],
    ])('%s', (_case, lastStatus, lastSucceededAt, failingSince, expected) => {
        expect(
            failingForLabel(
                { last_status: lastStatus, last_succeeded_at: lastSucceededAt, failing_since: failingSince },
                now
            )
        ).toEqual(expected)
    })

    it.each<[string, string | null, CheckTypeEnumApi, string, string]>([
        [
            'a named check is labelled by its name',
            'orders_are_fresh',
            CheckTypeEnumApi.Freshness,
            '',
            'orders_are_fresh',
        ],
        ['an unnamed check describes its assertion', null, CheckTypeEnumApi.NotNull, 'email', 'Not null on email'],
        ['a check on no column names the type alone', null, CheckTypeEnumApi.RowCount, '', 'Row count'],
    ])('%s', (_case, checkName, checkType, columnName, expected) => {
        expect(checkRunDisplayName({ check_name: checkName, check_type: checkType, column_name: columnName })).toEqual(
            expected
        )
    })

    it('sorts the runs that need a person above the ones that do not', () => {
        const runs = [{ status: 'passed' }, { status: 'skipped' }, { status: 'errored' }, { status: 'failed' }]

        expect([...runs].sort(byStatusAttention).map((run) => run.status)).toEqual([
            'failed',
            'errored',
            'skipped',
            'passed',
        ])
    })

    it.each<[string, CheckTypeEnumApi, number | null, Record<string, unknown> | null, string, string | null]>([
        [
            'a freshness run reads as a duration with its limit',
            CheckTypeEnumApi.Freshness,
            147117,
            { max_age_minutes: 2160 },
            '1d\u00a016h old',
            'Newest row is 147,117 seconds old. The limit is 1d\u00a012h.',
        ],
        [
            'a freshness run without a config snapshot omits the limit',
            CheckTypeEnumApi.Freshness,
            147117,
            null,
            '1d\u00a016h old',
            'Newest row is 147,117 seconds old.',
        ],
        [
            'a row count run names the bound it is held to',
            CheckTypeEnumApi.RowCount,
            1493355,
            { min: 1000000, max: 2000000 },
            '1,493,355\u00a0rows',
            '1,493,355\u00a0rows. The limit is between 1,000,000 and 2,000,000\u00a0rows.',
        ],
        [
            'a row count run with one bound names only that one',
            CheckTypeEnumApi.RowCount,
            12,
            { max: 10 },
            '12\u00a0rows',
            '12\u00a0rows. The limit is at most 10\u00a0rows.',
        ],
        [
            'a row count run with a bound of one reads in the singular',
            CheckTypeEnumApi.RowCount,
            0,
            { min: 1 },
            '0\u00a0rows',
            '0\u00a0rows. The limit is at least 1\u00a0row.',
        ],
        [
            'a freshness run whose newest row is ahead of the clock says so',
            CheckTypeEnumApi.Freshness,
            -3600,
            { max_age_minutes: 2160 },
            '1h in the future',
            'Newest row is 3,600 seconds in the future. The limit is 1d\u00a012h.',
        ],
        ['a not null run counts null rows', CheckTypeEnumApi.NotNull, 7, null, '7\u00a0null rows', null],
        [
            'a unique run counts duplicate values, singular at one',
            CheckTypeEnumApi.Unique,
            1,
            null,
            '1\u00a0duplicate value',
            null,
        ],
        [
            'a custom SQL run counts the rows its query returned',
            CheckTypeEnumApi.CustomSql,
            0,
            null,
            '0\u00a0rows returned',
            null,
        ],
        ['a run with nothing observed shows a dash', CheckTypeEnumApi.Freshness, null, null, '-', null],
    ])('%s', (_case, checkType, observedValue, checkConfig, label, tooltip) => {
        expect(
            runResultCell({ check_type: checkType, observed_value: observedValue, check_config: checkConfig })
        ).toEqual({ label, tooltip })
    })
})
