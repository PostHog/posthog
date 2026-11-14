import { render } from '@testing-library/react'

import { ActivityChange, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { ActivityScope } from '~/types'

import { dataQualityCheckActivityDescriber, dataQualityCheckScheduleActivityDescriber } from './activityDescriber'

const textOf = (description: JSX.Element | string | null): string => {
    if (!description || typeof description === 'string') {
        return description || ''
    }
    return render(description).container.textContent || ''
}

const change = (scope: ActivityScope, field: string, before: unknown, after: unknown): ActivityChange => ({
    type: scope,
    action: 'changed',
    field,
    before: before as ActivityChange['before'],
    after: after as ActivityChange['after'],
})

const logItem = (overrides: Partial<ActivityLogItem>): ActivityLogItem => ({
    activity: 'updated',
    created_at: '2026-08-06T10:00:00Z',
    scope: 'DataQualityCheck',
    item_id: 'check-uuid',
    user: { first_name: 'Ada', last_name: 'Lovelace', email: 'ada@example.com' },
    detail: { merge: null, trigger: null, changes: null, name: 'orders_customer_id_not_null' },
    ...overrides,
})

describe('dataQualityCheckActivityDescriber', () => {
    it('describes a created check', () => {
        const result = dataQualityCheckActivityDescriber(logItem({ activity: 'created' }))
        expect(textOf(result.description)).toContain('created the check orders_customer_id_not_null')
    })

    it('describes a severity change in the labels the editor shows', () => {
        const result = dataQualityCheckActivityDescriber(
            logItem({
                detail: {
                    merge: null,
                    trigger: null,
                    name: 'orders_customer_id_not_null',
                    changes: [change(ActivityScope.DATA_QUALITY_CHECK, 'severity', 'error', 'warn')],
                },
            })
        )
        expect(textOf(result.description)).toContain('changed the severity from error to warning')
    })

    it('keeps an update that only changed the check type', () => {
        const result = dataQualityCheckActivityDescriber(
            logItem({
                detail: {
                    merge: null,
                    trigger: null,
                    name: 'orders_customer_id_not_null',
                    changes: [change(ActivityScope.DATA_QUALITY_CHECK, 'check_type', 'not_null', 'unique')],
                },
            })
        )
        expect(textOf(result.description)).toContain('changed the check type from Not null to Unique')
    })

    it('shows an empty column as empty', () => {
        const result = dataQualityCheckActivityDescriber(
            logItem({
                detail: {
                    merge: null,
                    trigger: null,
                    name: 'orders_customer_id_not_null',
                    changes: [change(ActivityScope.DATA_QUALITY_CHECK, 'column_name', '', 'customer_id')],
                },
            })
        )
        expect(textOf(result.description)).toContain('changed the column from empty to customer_id')
    })

    it('keeps an update to a field without a custom description', () => {
        const result = dataQualityCheckActivityDescriber(
            logItem({
                detail: {
                    merge: null,
                    trigger: null,
                    name: 'orders_customer_id_not_null',
                    changes: [change(ActivityScope.DATA_QUALITY_CHECK, 'reasoning', 'old', 'new')],
                },
            })
        )
        expect(result.description).not.toBeNull()
    })

    it('hides an update that only touched fields the runner writes', () => {
        const result = dataQualityCheckActivityDescriber(
            logItem({
                detail: {
                    merge: null,
                    trigger: null,
                    name: 'orders_customer_id_not_null',
                    changes: [change(ActivityScope.DATA_QUALITY_CHECK, 'failing_since', null, '2026-08-06T10:00:00Z')],
                },
            })
        )
        expect(result.description).toBeNull()
    })
})

describe('dataQualityCheckScheduleActivityDescriber', () => {
    it('describes a frequency change', () => {
        const result = dataQualityCheckScheduleActivityDescriber(
            logItem({
                scope: 'DataQualityCheckSchedule',
                detail: {
                    merge: null,
                    trigger: null,
                    name: 'view check schedule on orders',
                    changes: [change(ActivityScope.DATA_QUALITY_CHECK_SCHEDULE, 'interval', '24hour', '6hour')],
                },
            })
        )
        expect(textOf(result.description)).toContain('changed the run frequency from daily to every 6 hours')
    })

    it('describes turning the schedule off', () => {
        const result = dataQualityCheckScheduleActivityDescriber(
            logItem({
                scope: 'DataQualityCheckSchedule',
                detail: {
                    merge: null,
                    trigger: null,
                    name: 'view check schedule on orders',
                    changes: [change(ActivityScope.DATA_QUALITY_CHECK_SCHEDULE, 'enabled', true, false)],
                },
            })
        )
        expect(textOf(result.description)).toContain('turned the schedule off')
    })
})
