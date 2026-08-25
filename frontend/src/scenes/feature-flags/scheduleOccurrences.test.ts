import { MOCK_DEFAULT_BASIC_USER } from 'lib/api.mock'

import { dayjs } from 'lib/dayjs'

import {
    FeatureFlagType,
    RecurrenceInterval,
    ScheduledChangeModels,
    ScheduledChangeOperationType,
    ScheduledChangePayload,
    ScheduledChangeRequestState,
    ScheduledChangeType,
} from '~/types'

import { OCCURRENCE_CAP, expandScheduleOccurrences } from './scheduleOccurrences'

const NOW = dayjs('2026-01-01T00:00:00Z')

let nextId = 1

function change(overrides: Partial<ScheduledChangeType> & { payload: ScheduledChangePayload }): ScheduledChangeType {
    return {
        id: nextId++,
        team_id: 1,
        record_id: 1,
        model_name: ScheduledChangeModels.FeatureFlag,
        scheduled_at: NOW.add(1, 'day').toISOString(),
        executed_at: null,
        failure_reason: null,
        created_at: null,
        created_by: MOCK_DEFAULT_BASIC_USER,
        is_recurring: false,
        recurrence_interval: null,
        cron_expression: null,
        last_executed_at: null,
        end_date: null,
        change_request: null,
        ...overrides,
    }
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
        nextId = 1
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
    ])('excludes $name schedules', ({ overrides }) => {
        const schedules = [change({ payload: STATUS_ON, ...overrides })]

        expect(expandScheduleOccurrences(schedules, flag(), NOW)).toEqual([])
    })
})
