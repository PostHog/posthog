import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeReport } from 'products/signals/frontend/inbox/__mocks__/inboxMocks'

import { todayBriefingLogic } from './todayBriefingLogic'
import { todayReportQueueLogic } from './todayReportQueueLogic'
import { makeBriefing, makeHighlights } from './todayTestFixtures'

describe('todayReportQueueLogic', () => {
    it('keeps the report order the person opened from while a later briefing names other reports', async () => {
        const briefing = makeBriefing()
        briefing.items[0].key = 'report:z'
        briefing.paragraphs[0][0].item_key = 'report:z'
        let briefingResponse: [number, any] = [404, { detail: 'Not found.' }]
        useMocks({
            get: {
                '/api/projects/:team_id/signals/reports/for_you/': {
                    results: [makeReport({ id: 'a' }), makeReport({ id: 'b' })],
                    count: 2,
                },
                '/api/projects/:team_id/today/highlights/': makeHighlights(),
                '/api/projects/:team_id/today/briefing/': () => briefingResponse,
            },
        })
        initKeaTests()
        const logic = todayReportQueueLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        router.actions.push('/project/997/home/reports/b')
        briefingResponse = [200, briefing]
        await expectLogic(logic, () => {
            todayBriefingLogic.actions.loadPersonalBriefing()
        })
            .toFinishAllListeners()
            .toMatchValues({ reportQueueIds: ['a', 'b', 'z'], reportPosition: 2 })

        router.actions.push('/project/997/home')
        expect(logic.values.reportQueueIds).toEqual(['z'])
    })
})
