import { render } from '@testing-library/react'

import { ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

import { batchExportActivityDescriber, formatSchedule } from './activityDescriptions'

function makeLogItem(overrides: Partial<ActivityLogItem> & { detail: ActivityLogItem['detail'] }): ActivityLogItem {
    return {
        user: { first_name: 'Max', last_name: 'Hog', email: 'max@posthog.com' },
        activity: 'updated',
        created_at: '2026-03-01T00:00:00Z',
        scope: ActivityScope.BATCH_EXPORT,
        item_id: 'abc-123',
        ...overrides,
    }
}

/** Render the describer's JSX output to a DOM and extract the visible text for assertions. */
function describeText(logItem: ActivityLogItem): string {
    const { description } = batchExportActivityDescriber(logItem)
    if (!description) {
        return ''
    }
    const { container } = render(<>{description}</>)
    return container.textContent ?? ''
}

describe('batch export activity descriptions', () => {
    beforeEach(() => {
        // The describer returns JSX containing <Link> components which rely on kea-router
        initKeaTests()
    })

    describe('formatSchedule', () => {
        it.each([
            ['hourly', 'hour', undefined, undefined],
            ['every 5 minutes', 'every 5 minutes', undefined, undefined],
            ['daily', 'day', undefined, undefined],
            ['daily at 01:00', 'day', 3600, undefined],
            ['daily at 00:00 (UTC)', 'day', 0, 'UTC'],
            ['daily at 03:00 (Asia/Muscat)', 'day', 10800, 'Asia/Muscat'],
            ['weekly', 'week', undefined, undefined],
            ['weekly on Sunday at 00:00', 'week', 0, undefined],
            ['weekly on Monday at 01:00', 'week', 90000, undefined],
            ['weekly on Monday at 01:00 (UTC)', 'week', 90000, 'UTC'],
            ['weekly on Saturday at 23:00 (US/Pacific)', 'week', 6 * 86400 + 23 * 3600, 'US/Pacific'],
        ])('formats as "%s"', (expected, interval, offset, timezone) => {
            expect(formatSchedule(interval, offset, timezone)).toBe(expected)
        })

        it('returns null for undefined interval', () => {
            expect(formatSchedule(undefined, undefined, undefined)).toBeNull()
        })
    })

    describe('batchExportActivityDescriber', () => {
        it('describes creation', () => {
            const text = describeText(
                makeLogItem({
                    activity: 'created',
                    detail: { name: "'My S3 Export' (S3)", merge: null, trigger: null, changes: [] },
                })
            )
            expect(text).toContain(`Max Hog created batch export 'My S3 Export' (S3)`)
        })

        it('describes deletion', () => {
            const text = describeText(
                makeLogItem({
                    detail: {
                        name: "'My S3 Export' (S3)",
                        merge: null,
                        trigger: null,
                        changes: [
                            { type: ActivityScope.BATCH_EXPORT, action: 'changed', field: 'deleted', after: true },
                        ],
                    },
                })
            )
            expect(text).toContain(`Max Hog deleted batch export 'My S3 Export' (S3)`)
        })

        it('describes enabling (paused=false)', () => {
            const text = describeText(
                makeLogItem({
                    detail: {
                        name: "'My S3 Export' (S3)",
                        merge: null,
                        trigger: null,
                        changes: [
                            {
                                type: ActivityScope.BATCH_EXPORT,
                                action: 'changed',
                                field: 'enabled',
                                before: true,
                                after: false,
                            },
                        ],
                    },
                })
            )
            expect(text).toContain(`Max Hog enabled batch export 'My S3 Export' (S3)`)
        })

        it('describes disabling (paused=true)', () => {
            const text = describeText(
                makeLogItem({
                    detail: {
                        name: "'My S3 Export' (S3)",
                        merge: null,
                        trigger: null,
                        changes: [
                            {
                                type: ActivityScope.BATCH_EXPORT,
                                action: 'changed',
                                field: 'enabled',
                                before: false,
                                after: true,
                            },
                        ],
                    },
                })
            )
            expect(text).toContain(`Max Hog disabled batch export 'My S3 Export' (S3)`)
        })

        it('describes a name change with before and after', () => {
            const text = describeText(
                makeLogItem({
                    detail: {
                        name: "'New Name' (S3)",
                        merge: null,
                        trigger: null,
                        changes: [
                            {
                                type: ActivityScope.BATCH_EXPORT,
                                action: 'changed',
                                field: 'name',
                                before: "'Old Name' (S3)",
                                after: "'New Name' (S3)",
                            },
                        ],
                    },
                })
            )
            expect(text).toContain(
                `Max Hog changed the name from 'Old Name' (S3) to 'New Name' (S3) for batch export 'New Name' (S3)`
            )
        })

        it('describes a model change', () => {
            const text = describeText(
                makeLogItem({
                    detail: {
                        name: "'My S3 Export' (S3)",
                        merge: null,
                        trigger: null,
                        changes: [
                            {
                                type: ActivityScope.BATCH_EXPORT,
                                action: 'changed',
                                field: 'model',
                                before: 'events',
                                after: 'persons',
                            },
                        ],
                    },
                })
            )
            expect(text).toContain(
                `Max Hog changed the model from events to persons for batch export 'My S3 Export' (S3)`
            )
        })

        describe('schedule changes', () => {
            type ChangeValue = string | number | boolean | null | undefined
            type ScheduleChange = { field: string; before: ChangeValue; after: ChangeValue }

            function change(field: string, before: ChangeValue, after: ChangeValue): ScheduleChange {
                return { field, before, after }
            }

            function describeSchedule(changes: ScheduleChange[]): string {
                return describeText(
                    makeLogItem({
                        detail: {
                            name: "'My S3 Export' (S3)",
                            merge: null,
                            trigger: null,
                            changes: changes.map((c) => ({
                                type: ActivityScope.BATCH_EXPORT,
                                action: 'changed' as const,
                                ...c,
                            })),
                        },
                    })
                )
            }

            // hourly → daily
            it.each([
                {
                    name: 'hourly to daily, defaults unchanged',
                    changes: [change('interval', 'hour', 'day')],
                    expected: 'changed the schedule from hourly to daily at 00:00 (UTC)',
                },
                {
                    name: 'hourly to daily, also changing timezone',
                    changes: [change('interval', 'hour', 'day'), change('timezone', 'UTC', 'Asia/Muscat')],
                    expected: 'changed the schedule from hourly to daily at 00:00 (Asia/Muscat)',
                },
                {
                    name: 'hourly to daily, also changing start time',
                    changes: [change('interval', 'hour', 'day'), change('interval_offset', null, 10800)],
                    expected: 'changed the schedule from hourly to daily at 03:00 (UTC)',
                },
                {
                    name: 'hourly to daily, changing both timezone and start time',
                    changes: [
                        change('interval', 'hour', 'day'),
                        change('interval_offset', null, 10800),
                        change('timezone', 'UTC', 'Asia/Muscat'),
                    ],
                    expected: 'changed the schedule from hourly to daily at 03:00 (Asia/Muscat)',
                },
                // hourly → weekly
                {
                    name: 'hourly to weekly, defaults unchanged',
                    changes: [change('interval', 'hour', 'week')],
                    expected: 'changed the schedule from hourly to weekly on Sunday at 00:00 (UTC)',
                },
                {
                    name: 'hourly to weekly, also changing timezone',
                    changes: [change('interval', 'hour', 'week'), change('timezone', 'UTC', 'US/Pacific')],
                    expected: 'changed the schedule from hourly to weekly on Sunday at 00:00 (US/Pacific)',
                },
                {
                    name: 'hourly to weekly, also changing start time',
                    changes: [change('interval', 'hour', 'week'), change('interval_offset', null, 90000)],
                    expected: 'changed the schedule from hourly to weekly on Monday at 01:00 (UTC)',
                },
                {
                    name: 'hourly to weekly, changing both timezone and start time',
                    changes: [
                        change('interval', 'hour', 'week'),
                        change('interval_offset', null, 90000),
                        change('timezone', 'UTC', 'US/Pacific'),
                    ],
                    expected: 'changed the schedule from hourly to weekly on Monday at 01:00 (US/Pacific)',
                },
                // daily ↔ weekly: both intervals support timezone and start time, so unchanged
                // fields may have non-default values — we can't assume defaults here and only
                // show what we know changed
                {
                    name: 'daily to weekly, defaults unchanged',
                    changes: [change('interval', 'day', 'week')],
                    expected: 'changed the schedule from daily to weekly',
                },
                {
                    name: 'daily to weekly, also changing timezone',
                    changes: [change('interval', 'day', 'week'), change('timezone', 'UTC', 'Europe/London')],
                    expected: 'changed the schedule from daily (UTC) to weekly (Europe/London)',
                },
                {
                    name: 'daily to weekly, also changing start time',
                    changes: [change('interval', 'day', 'week'), change('interval_offset', 10800, 90000)],
                    expected: 'changed the schedule from daily at 03:00 to weekly on Monday at 01:00',
                },
                {
                    name: 'daily to weekly, changing both timezone and start time',
                    changes: [
                        change('interval', 'day', 'week'),
                        change('interval_offset', 10800, 90000),
                        change('timezone', 'UTC', 'Europe/London'),
                    ],
                    expected:
                        'changed the schedule from daily at 03:00 (UTC) to weekly on Monday at 01:00 (Europe/London)',
                },
                // weekly → daily (same caveat as daily → weekly above)
                {
                    name: 'weekly to daily, defaults unchanged',
                    changes: [change('interval', 'week', 'day')],
                    expected: 'changed the schedule from weekly to daily',
                },
                {
                    name: 'weekly to daily, also changing timezone',
                    changes: [change('interval', 'week', 'day'), change('timezone', 'Europe/London', 'UTC')],
                    expected: 'changed the schedule from weekly (Europe/London) to daily (UTC)',
                },
                {
                    name: 'weekly to daily, also changing start time',
                    changes: [change('interval', 'week', 'day'), change('interval_offset', 90000, 7200)],
                    expected: 'changed the schedule from weekly on Monday at 01:00 to daily at 02:00',
                },
                {
                    name: 'weekly to daily, changing both timezone and start time',
                    changes: [
                        change('interval', 'week', 'day'),
                        change('interval_offset', 90000, 7200),
                        change('timezone', 'Europe/London', 'UTC'),
                    ],
                    expected:
                        'changed the schedule from weekly on Monday at 01:00 (Europe/London) to daily at 02:00 (UTC)',
                },
                // daily/weekly → hourly (sub-day suppresses offset and timezone)
                {
                    name: 'daily to hourly, offset and timezone suppressed',
                    changes: [
                        change('interval', 'day', 'hour'),
                        change('interval_offset', 10800, null),
                        change('timezone', 'Asia/Muscat', 'UTC'),
                    ],
                    expected: 'changed the schedule from daily at 03:00 (Asia/Muscat) to hourly',
                },
                {
                    name: 'weekly to hourly, offset and timezone suppressed',
                    changes: [
                        change('interval', 'week', 'hour'),
                        change('interval_offset', 90000, null),
                        change('timezone', 'US/Pacific', 'UTC'),
                    ],
                    expected: 'changed the schedule from weekly on Monday at 01:00 (US/Pacific) to hourly',
                },
                // no interval change — individual field descriptions
                {
                    name: 'only timezone changes',
                    changes: [change('timezone', 'UTC', 'Asia/Muscat')],
                    expected: 'changed the schedule timezone from UTC to Asia/Muscat',
                },
                {
                    name: 'only start time changes',
                    changes: [change('interval_offset', 0, 10800)],
                    expected: 'changed the schedule start time from 00:00 to 03:00',
                },
                {
                    name: 'start time changes from null (default midnight)',
                    changes: [change('interval_offset', null, 3600)],
                    expected: 'changed the schedule start time from 00:00 to 01:00',
                },
                {
                    name: 'both timezone and start time change',
                    changes: [change('timezone', 'UTC', 'Asia/Muscat'), change('interval_offset', 0, 10800)],
                    expected: 'changed schedule timezone from UTC to Asia/Muscat',
                    expectedAlso: 'changed schedule start time from 00:00 to 03:00',
                },
            ])(
                '$name',
                ({
                    changes,
                    expected,
                    expectedAlso,
                }: {
                    changes: ScheduleChange[]
                    expected: string
                    expectedAlso?: string
                }) => {
                    const text = describeSchedule(changes)
                    expect(text).toContain(expected)
                    if (expectedAlso) {
                        expect(text).toContain(expectedAlso)
                    }
                }
            )
        })

        it('shows multiple non-schedule changes as a bulleted list', () => {
            const text = describeText(
                makeLogItem({
                    detail: {
                        name: "'My S3 Export' (S3)",
                        merge: null,
                        trigger: null,
                        changes: [
                            {
                                type: ActivityScope.BATCH_EXPORT,
                                action: 'changed',
                                field: 'name',
                                before: 'Old',
                                after: 'New',
                            },
                            {
                                type: ActivityScope.BATCH_EXPORT,
                                action: 'changed',
                                field: 'interval',
                                before: 'hour',
                                after: 'day',
                            },
                        ],
                    },
                })
            )
            expect(text).toContain(`Max Hog updated batch export 'My S3 Export' (S3)`)
            expect(text).toContain('changed name from Old to New')
            expect(text).toContain('changed schedule from hourly to daily')
        })

        it('shows generic update when no changes are present', () => {
            const text = describeText(
                makeLogItem({
                    detail: { name: "'My S3 Export' (S3)", merge: null, trigger: null, changes: [] },
                })
            )
            expect(text).toContain(`Max Hog updated batch export 'My S3 Export' (S3)`)
        })
    })
})
