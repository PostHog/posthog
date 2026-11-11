import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeReport } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'

import { todayLogic } from './todayLogic'
import { todayReportQueueLogic } from './todayReportQueueLogic'
import { makeHighlights } from './todayTestFixtures'

describe('todayReportQueueLogic', () => {
    it('keeps the report order the person opened from while a later load shows other reports', async () => {
        let reports = [makeReport({ id: 'a' }), makeReport({ id: 'b' })]
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/': () => [200, { results: reports, count: reports.length }],
                '/api/projects/:team_id/today/highlights/': makeHighlights(),
            },
        })
        initKeaTests()
        const logic = todayReportQueueLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        router.actions.push('/project/997/home/reports/b')
        reports = [makeReport({ id: 'z' })]
        await expectLogic(logic, () => {
            todayLogic.actions.loadTopReports()
        })
            .toFinishAllListeners()
            .toMatchValues({ reportQueueIds: ['a', 'b', 'z'], reportPosition: 2 })

        router.actions.push('/project/997/home')
        expect(logic.values.reportQueueIds).toEqual(['z'])
    })
})
