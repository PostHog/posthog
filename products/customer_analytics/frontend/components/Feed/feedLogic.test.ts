import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { UserType } from '~/types'

import { SignalReportStatus } from 'products/signals/frontend/inbox/types'

import { CUSTOMER_ANALYTICS_SCOUT_PREFIX, feedLogic } from './feedLogic'

describe('feedLogic', () => {
    let logic: ReturnType<typeof feedLogic.build>
    let lastParams: URLSearchParams | null = null

    beforeEach(() => {
        lastParams = null
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/': ({ request }) => {
                    lastParams = new URL(request.url).searchParams
                    return [200, { results: [], count: 0 }]
                },
                '/api/projects/:team_id/signals/scout/configs/': () => [
                    200,
                    [
                        { id: '1', skill_name: 'signals-scout-customer-analytics' },
                        { id: '2', skill_name: 'signals-scout-customer-analytics-billing-and-usage' },
                        { id: '3', skill_name: 'signals-scout-error-tracking' },
                    ],
                ],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('always scopes the list to the customer analytics scout prefix', async () => {
        logic = feedLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadReports', 'loadReportsSuccess'])

        expect(lastParams?.get('scout_prefix')).toBe(CUSTOMER_ANALYTICS_SCOUT_PREFIX)
        expect(lastParams?.get('status')).toBeNull()
        expect(lastParams?.get('suggested_reviewers')).toBeNull()
    })

    it('applies the status and my-reports filters to the request', async () => {
        logic = feedLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadReportsSuccess'])
        userLogic.actions.loadUserSuccess({ id: 7, uuid: 'user-uuid-7', email: 'me@example.com' } as UserType)

        await expectLogic(logic, () => {
            logic.actions.setStatusFilter(SignalReportStatus.READY)
            logic.actions.setMyReportsOnly(true)
        }).toFinishAllListeners()

        expect(lastParams?.get('scout_prefix')).toBe(CUSTOMER_ANALYTICS_SCOUT_PREFIX)
        expect(lastParams?.get('status')).toBe('ready')
        expect(lastParams?.get('suggested_reviewers')).toBe('user-uuid-7')
    })

    it('applies the search, sort, priority and scout filters to the request', async () => {
        logic = feedLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadReportsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.setSearchQuery('  churn  ')
            logic.actions.setSort('created_at', 'desc')
            logic.actions.togglePriority('P0')
            logic.actions.togglePriority('P1')
            logic.actions.toggleScout('signals-scout-customer-analytics-billing-and-usage')
        }).toFinishAllListeners()

        expect(lastParams?.get('search')).toBe('churn')
        expect(lastParams?.get('ordering')).toBe('-created_at,status,-updated_at')
        expect(lastParams?.get('priority')).toBe('P0,P1')
        expect(lastParams?.get('scout')).toBe('signals-scout-customer-analytics-billing-and-usage')
    })

    it('offers only customer analytics scouts in the scout picker', async () => {
        logic = feedLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadScoutConfigsSuccess'])

        expect(logic.values.scoutNames).toEqual([
            'signals-scout-customer-analytics',
            'signals-scout-customer-analytics-billing-and-usage',
        ])
    })

    it('clears every filter at once, but keeps the chosen sort', async () => {
        logic = feedLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadReportsSuccess'])

        await expectLogic(logic, () => {
            logic.actions.setSearchQuery('churn')
            logic.actions.setStatusFilter(SignalReportStatus.READY)
            logic.actions.togglePriority('P0')
            logic.actions.toggleScout('signals-scout-customer-analytics')
            logic.actions.setMyReportsOnly(true)
            logic.actions.setSort('created_at', 'desc')
        }).toFinishAllListeners()
        expect(logic.values.hasActiveFilters).toBe(true)

        await expectLogic(logic, () => logic.actions.clearFilters()).toFinishAllListeners()

        expect(logic.values.hasActiveFilters).toBe(false)
        expect(lastParams?.get('search')).toBeNull()
        expect(lastParams?.get('status')).toBeNull()
        expect(lastParams?.get('priority')).toBeNull()
        expect(lastParams?.get('scout')).toBeNull()
        expect(lastParams?.get('suggested_reviewers')).toBeNull()
        // Sort reorders rather than hides, so clearing filters must not reset it.
        expect(lastParams?.get('ordering')).toBe('-created_at,status,-updated_at')
    })
})
