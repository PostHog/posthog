import { dayjs } from 'lib/dayjs'

import {
    FeatureFlagType,
    RecurrenceInterval,
    ScheduledChangeOperationType,
    ScheduledChangePayload,
    ScheduledChangeRequestState,
    ScheduledChangeType,
} from '~/types'

import { makeScheduledChange, resetScheduledChangeIds } from './makeScheduledChange'
import { OCCURRENCE_CAP, expandScheduleOccurrences } from './scheduleOccurrences'

const NOW = dayjs('2026-01-01T00:00:00Z')

function change(overrides: Partial<ScheduledChangeType> & { payload: ScheduledChangePayload }): ScheduledChangeType {
    return makeScheduledChange({ scheduled_at: NOW.add(1, 'day').toISOString(), ...overrides })
}

function conditionPayload(rolloutPercentage: number): ScheduledChangePayload {
    return {
        operation: ScheduledChangeOperationType.AddReleaseCondition,
        value: { groups: [{ properties: [], rollout_percentage: rolloutPercentage, variant: null }] },
    }
}

const STATUS_ON: ScheduledChangePayload = { operation: ScheduledChangeOperationType.UpdateStatus, value: true }

function flag(
    overrides: Partial<Pick<FeatureFlagType, 'active' | 'filters'>> = {}
): Pick<FeatureFlagType, 'active' | 'filters'> {
    return {
        active: true,
        filters: {
            groups: [{ properties: [], rollout_percentage: 10, variant: null }],
            multivariate: null,
        },
        ...overrides,
    }
}

describe('expandScheduleOccurrences', () => {
    beforeEach(() => {
        resetScheduledChangeIds()
    })

    it('projects a rollout ramp cumulatively and in chronological order', () => {
        // Deliberately out of order: expansion must sort by time, not input order.
        const schedules = [
            change({ payload: conditionPayload(75), scheduled_at: NOW.add(3, 'day').toISOString() }),
            change({ payload: conditionPayload(25), scheduled_at: NOW.add(1, 'day').toISOString() }),
            change({ payload: conditionPayload(100), scheduled_at: NOW.add(4, 'day').toISOString() }),
            change({ payload: conditionPayload(50), scheduled_at: NOW.add(2, 'day').toISOString() }),
        ]

        const occurrences = expandScheduleOccurrences(schedules, flag(), NOW)

        expect(occurrences.map((o) => o.projected.rolloutPercentage)).toEqual([25, 50, 75, 100])
        expect(occurrences.map((o) => o.addedRolloutPercentage)).toEqual([25, 50, 75, 100])
        expect(occurrences.map((o) => o.timestamp)).toEqual([
            NOW.add(1, 'day').toISOString(),
            NOW.add(2, 'day').toISOString(),
            NOW.add(3, 'day').toISOString(),
            NOW.add(4, 'day').toISOString(),
        ])
    })

    it('carries status, rollout, and variant projections through a mixed plan', () => {
        const schedules = [
            change({
                payload: { operation: ScheduledChangeOperationType.UpdateStatus, value: false },
                scheduled_at: NOW.add(1, 'day').toISOString(),
            }),
            change({ payload: conditionPayload(5), scheduled_at: NOW.add(2, 'day').toISOString() }),
            change({
                payload: {
                    operation: ScheduledChangeOperationType.UpdateVariants,
                    value: {
                        variants: [
                            { key: 'a', rollout_percentage: 50 },
                            { key: 'b', rollout_percentage: 50 },
                        ],
                    },
                },
                scheduled_at: NOW.add(3, 'day').toISOString(),
            }),
        ]

        const occurrences = expandScheduleOccurrences(schedules, flag(), NOW)

        expect(occurrences.map((o) => o.projected)).toEqual([
            { active: false, rolloutPercentage: 10, variantCount: null },
            // A 5% condition does not lower the flag's existing 10% max rollout.
            { active: false, rolloutPercentage: 10, variantCount: null },
            { active: false, rolloutPercentage: 10, variantCount: 2 },
        ])
    })

    it.each([
        {
            name: 'a condition set with no rollout percentage as 100%',
            groups: [{ properties: [], rollout_percentage: null, variant: null }],
            expected: 100,
        },
        { name: 'no condition sets as unknown', groups: [], expected: null },
    ])('reads $name', ({ groups, expected }) => {
        // Null means the set matches all of its targets. Coercing it to 0 would floor the step
        // line and describe a scheduled condition as a 0% rollout.
        const schedules = [
            change({
                payload: { operation: ScheduledChangeOperationType.AddReleaseCondition, value: { groups } },
            }),
        ]

        const occurrences = expandScheduleOccurrences(schedules, flag({ filters: { groups, multivariate: null } }), NOW)

        expect(occurrences[0].addedRolloutPercentage).toEqual(expected)
        expect(occurrences[0].projected.rolloutPercentage).toEqual(expected)
    })

    it('expands a fixed-interval recurring schedule up to its end date', () => {
        const schedules = [
            change({
                payload: STATUS_ON,
                is_recurring: true,
                recurrence_interval: RecurrenceInterval.Daily,
                scheduled_at: NOW.add(1, 'day').toISOString(),
                end_date: NOW.add(3, 'day').add(12, 'hour').toISOString(),
            }),
        ]

        const occurrences = expandScheduleOccurrences(schedules, flag(), NOW)

        expect(occurrences.map((o) => o.timestamp)).toEqual([
            NOW.add(1, 'day').toISOString(),
            NOW.add(2, 'day').toISOString(),
            NOW.add(3, 'day').toISOString(),
        ])
    })

    it('stops recurring expansion at the horizon', () => {
        const schedules = [
            change({
                payload: STATUS_ON,
                is_recurring: true,
                recurrence_interval: RecurrenceInterval.Monthly,
                scheduled_at: NOW.add(10, 'day').toISOString(),
            }),
        ]

        // Jan 11, Feb 11, and Mar 11 fall inside the 90-day horizon; Apr 11 does not.
        expect(expandScheduleOccurrences(schedules, flag(), NOW)).toHaveLength(3)
    })

    it('clamps month-end recurring dates iteratively, matching the backend', () => {
        // A monthly schedule starting Jan 31 must not restore the 31st after a short month: the
        // backend advances from the previous run (Jan 31 -> Feb 28 -> Mar 28), so the projection must too.
        const schedules = [
            change({
                payload: STATUS_ON,
                is_recurring: true,
                recurrence_interval: RecurrenceInterval.Monthly,
                scheduled_at: dayjs('2026-01-31T09:00:00Z').toISOString(),
            }),
        ]

        const occurrences = expandScheduleOccurrences(schedules, flag(), NOW)

        expect(occurrences.map((o) => o.timestamp)).toEqual([
            '2026-01-31T09:00:00.000Z',
            '2026-02-28T09:00:00.000Z',
            '2026-03-28T09:00:00.000Z',
        ])
    })

    it('gives a denied recurring cron schedule no occurrences', () => {
        // The next cron run after the denied one is not computed client-side.
        const schedules = [
            change({
                payload: STATUS_ON,
                is_recurring: true,
                cron_expression: '0 9 * * 1-5',
                change_request: { id: 'cr-5', state: ScheduledChangeRequestState.Expired },
            }),
        ]

        expect(expandScheduleOccurrences(schedules, flag(), NOW)).toEqual([])
    })

    it('caps the total number of occurrences', () => {
        const schedules = [
            change({
                payload: STATUS_ON,
                is_recurring: true,
                recurrence_interval: RecurrenceInterval.Daily,
                scheduled_at: NOW.add(1, 'day').toISOString(),
            }),
        ]

        expect(expandScheduleOccurrences(schedules, flag(), NOW)).toHaveLength(OCCURRENCE_CAP)
    })

    it('gives a cron schedule exactly one occurrence, at its next run', () => {
        const scheduledAt = NOW.add(1, 'day').toISOString()
        const schedules = [
            change({
                payload: STATUS_ON,
                is_recurring: true,
                cron_expression: '0 9 * * 1-5',
                scheduled_at: scheduledAt,
            }),
        ]

        const occurrences = expandScheduleOccurrences(schedules, flag(), NOW)

        expect(occurrences).toHaveLength(1)
        expect(occurrences[0].timestamp).toEqual(scheduledAt)
    })

    it.each([
        { state: ScheduledChangeRequestState.Pending, expected: true },
        { state: ScheduledChangeRequestState.Approved, expected: false },
    ])('marks occurrences with a $state approval request as needsApproval=$expected', ({ state, expected }) => {
        const schedules = [change({ payload: STATUS_ON, change_request: { id: 'cr-1', state } })]

        expect(expandScheduleOccurrences(schedules, flag(), NOW)[0].needsApproval).toBe(expected)
    })

    it.each([
        { state: ScheduledChangeRequestState.Approved, firstNeedsApproval: false },
        { state: ScheduledChangeRequestState.Pending, firstNeedsApproval: true },
    ])(
        're-gates every occurrence after the first of a $state gated recurring schedule',
        ({ state, firstNeedsApproval }) => {
            // The bound request covers one fire. The backend binds a fresh pending request to each
            // later occurrence, so an approved request must not project the whole ramp as certain.
            const schedules = [
                change({
                    payload: STATUS_ON,
                    is_recurring: true,
                    recurrence_interval: RecurrenceInterval.Daily,
                    scheduled_at: NOW.add(1, 'day').toISOString(),
                    change_request: { id: 'cr-1', state },
                }),
            ]

            const occurrences = expandScheduleOccurrences(schedules, flag(), NOW)

            expect(occurrences[0].needsApproval).toBe(firstNeedsApproval)
            expect(occurrences.slice(1).map((o) => o.needsApproval)).toEqual(occurrences.slice(1).map(() => true))
        }
    )

    it('leaves an ungated recurring schedule unmarked throughout', () => {
        const schedules = [
            change({
                payload: STATUS_ON,
                is_recurring: true,
                recurrence_interval: RecurrenceInterval.Daily,
                scheduled_at: NOW.add(1, 'day').toISOString(),
            }),
        ]

        const occurrences = expandScheduleOccurrences(schedules, flag(), NOW)

        expect(occurrences.every((o) => !o.needsApproval)).toBe(true)
    })

    it.each([{ state: ScheduledChangeRequestState.Rejected }, { state: ScheduledChangeRequestState.Expired }])(
        'drops a $state recurring occurrence but keeps expanding the rest',
        ({ state }) => {
            const schedules = [
                change({
                    payload: STATUS_ON,
                    is_recurring: true,
                    recurrence_interval: RecurrenceInterval.Daily,
                    scheduled_at: NOW.add(1, 'day').toISOString(),
                    change_request: { id: 'cr-denied', state },
                }),
            ]

            const occurrences = expandScheduleOccurrences(schedules, flag(), NOW)

            // The backend skips this occurrence and re-gates the next, so the timeline must not
            // project the denied change as applied; expansion resumes at the following day.
            expect(occurrences.map((o) => o.timestamp)).not.toContain(NOW.add(1, 'day').toISOString())
            expect(occurrences[0].timestamp).toEqual(NOW.add(2, 'day').toISOString())
        }
    )

    it.each([
        {
            name: 'paused recurring',
            overrides: { is_recurring: false, recurrence_interval: RecurrenceInterval.Daily },
        },
        { name: 'executed', overrides: { executed_at: NOW.subtract(1, 'day').toISOString() } },
        {
            name: 'rejected one-time',
            overrides: { change_request: { id: 'cr-2', state: ScheduledChangeRequestState.Rejected } },
        },
        {
            name: 'expired one-time',
            overrides: { change_request: { id: 'cr-3', state: ScheduledChangeRequestState.Expired } },
        },
        { name: 'unparseable scheduled_at', overrides: { scheduled_at: 'not-a-date' } },
        {
            // A recoverable failure leaves executed_at null with a now-past scheduled_at
            // (process_scheduled_changes: "leave executed_at=NULL to allow retries").
            name: 'past-due one-time',
            overrides: { scheduled_at: NOW.subtract(2, 'day').toISOString() },
        },
        {
            name: 'past-due cron',
            overrides: {
                scheduled_at: NOW.subtract(2, 'day').toISOString(),
                is_recurring: true,
                cron_expression: '0 9 * * 1-5',
            },
        },
        {
            name: 'recurring past its end date',
            overrides: {
                scheduled_at: NOW.subtract(10, 'day').toISOString(),
                is_recurring: true,
                recurrence_interval: RecurrenceInterval.Daily,
                end_date: NOW.subtract(5, 'day').toISOString(),
            },
        },
        {
            // The sweep advances scheduled_at without reading end_date, so a closed window can
            // hold a future date until the sweep reaches it and stamps executed_at.
            name: 'recurring past its end date with a future scheduled_at',
            overrides: {
                scheduled_at: NOW.add(1, 'day').toISOString(),
                is_recurring: true,
                recurrence_interval: RecurrenceInterval.Daily,
                end_date: NOW.subtract(1, 'day').toISOString(),
            },
        },
    ])('excludes $name schedules', ({ overrides }) => {
        const schedules = [change({ payload: STATUS_ON, ...overrides })]

        expect(expandScheduleOccurrences(schedules, flag(), NOW)).toEqual([])
    })

    it('catches a stalled recurring schedule up to its next fire, and re-gates it', () => {
        // The sweep leaves scheduled_at in the past when it defers on a conflicting approval, then
        // skips the missed fires. An approved request covered the fire that never happened, so the
        // caught-up occurrence must still read as needing approval.
        const schedules = [
            change({
                payload: STATUS_ON,
                is_recurring: true,
                recurrence_interval: RecurrenceInterval.Daily,
                scheduled_at: NOW.subtract(3, 'day').add(9, 'hour').toISOString(),
                change_request: { id: 'cr-1', state: ScheduledChangeRequestState.Approved },
            }),
        ]

        const occurrences = expandScheduleOccurrences(schedules, flag(), NOW)

        expect(occurrences[0].timestamp).toEqual(NOW.add(9, 'hour').toISOString())
        expect(occurrences[0].needsApproval).toBe(true)
    })

    it('clamps a stalled monthly schedule along the path the sweep took', () => {
        // Oct 31 monthly gives Nov 30, then Dec 30, then Jan 30. Adding three months to the origin
        // would restore the 31st and paint a date the flag never fires on.
        const schedules = [
            change({
                payload: STATUS_ON,
                is_recurring: true,
                recurrence_interval: RecurrenceInterval.Monthly,
                scheduled_at: dayjs('2025-10-31T09:00:00Z').toISOString(),
            }),
        ]

        const occurrences = expandScheduleOccurrences(schedules, flag(), NOW)

        expect(occurrences[0].timestamp).toEqual('2026-01-30T09:00:00.000Z')
    })
})
