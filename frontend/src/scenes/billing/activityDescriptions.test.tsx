import { render } from '@testing-library/react'

import { ActivityChange, ActivityLogDetail, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

import { initKeaTests } from '~/test/init'
import { ActivityScope } from '~/types'

import { billingActivityDescriber } from './activityDescriptions'

function makeDetail(name: string | null, changes: ActivityChange[] = []): ActivityLogDetail {
    return { merge: null, trigger: null, name, changes }
}

function makeLogItem(overrides: Partial<ActivityLogItem> & { detail: ActivityLogItem['detail'] }): ActivityLogItem {
    return {
        user: { first_name: 'Max', last_name: 'Hog', email: 'max@posthog.com' },
        activity: 'updated',
        created_at: '2026-03-01T00:00:00Z',
        scope: ActivityScope.BILLING,
        item_id: 'abc-123',
        ...overrides,
    }
}

function change(
    action: ActivityChange['action'],
    field: string,
    before: ActivityChange['before'] = null,
    after: ActivityChange['after'] = null
): ActivityChange {
    return { type: ActivityScope.BILLING, action, field, before, after }
}

function describeText(logItem: ActivityLogItem, asNotification?: boolean): string {
    const { description } = billingActivityDescriber(logItem, asNotification)
    if (!description) {
        return ''
    }
    const { container } = render(<>{description}</>)
    return container.textContent ?? ''
}

describe('billing activity descriptions', () => {
    beforeEach(() => {
        // The describer returns JSX containing a <Link> that relies on kea-router
        initKeaTests()
    })

    it('maps a known action name to its verb phrase', () => {
        const text = describeText(makeLogItem({ detail: makeDetail('Billing products activated') }))
        expect(text).toBe('Max Hog added products in billing')
    })

    it('renders both the American name and the British alias as "canceled a trial"', () => {
        expect(describeText(makeLogItem({ detail: makeDetail('Billing trial canceled') }))).toBe(
            'Max Hog canceled a trial in billing'
        )
        expect(describeText(makeLogItem({ detail: makeDetail('Billing trial cancelled') }))).toBe(
            'Max Hog canceled a trial in billing'
        )
    })

    it('falls back to a generic phrase for an unmapped action name', () => {
        const text = describeText(makeLogItem({ detail: makeDetail('Billing something new') }))
        expect(text).toBe('Max Hog updated billing in billing')
    })

    it('shows the after value for a created change', () => {
        const text = describeText(
            makeLogItem({ detail: makeDetail('Billing credits purchased', [change('created', 'credits', null, 5000)]) })
        )
        expect(text).toBe('Max Hog purchased credits in billing (credits: 5000)')
    })

    it('shows the before value for a deleted change', () => {
        const text = describeText(
            makeLogItem({
                detail: makeDetail('Billing next-period limit reset', [change('deleted', 'product_analytics', 100)]),
            })
        )
        expect(text).toBe('Max Hog reset a next-period spend limit in billing (product_analytics: 100)')
    })

    it('shows the before and after values for a changed field', () => {
        const text = describeText(
            makeLogItem({
                detail: makeDetail('Billing spend limits', [change('changed', 'product_analytics', 50, 100)]),
            })
        )
        expect(text).toBe('Max Hog updated the spend limits in billing (product_analytics from 50 to 100)')
    })

    it('lists field names when multiple fields change at once', () => {
        const text = describeText(
            makeLogItem({
                detail: makeDetail('Billing spend limits', [
                    change('changed', 'product_analytics', 50, 100),
                    change('changed', 'session_replay', 10, 20),
                ]),
            })
        )
        expect(text).toBe('Max Hog updated the spend limits in billing (product_analytics, session_replay)')
    })

    it('delegates non-updated activities to the default describer', () => {
        const text = describeText(makeLogItem({ activity: 'deleted', detail: makeDetail('Billing spend limits') }))
        expect(text).not.toContain('in billing')
    })
})
