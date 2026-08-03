import { expectLogic } from 'kea-test-utils'

import { SignalReportStatus } from 'scenes/inbox/types'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { UserType } from '~/types'

import { CUSTOMER_ANALYTICS_SCOUT_NAMES, feedLogic } from './feedLogic'

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
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('always scopes the list to the customer analytics scouts', async () => {
        logic = feedLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadReports', 'loadReportsSuccess'])

        expect(lastParams?.get('scout')).toBe(CUSTOMER_ANALYTICS_SCOUT_NAMES.join(','))
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

        expect(lastParams?.get('scout')).toBe(CUSTOMER_ANALYTICS_SCOUT_NAMES.join(','))
        expect(lastParams?.get('status')).toBe('ready')
        expect(lastParams?.get('suggested_reviewers')).toBe('user-uuid-7')
    })
})
