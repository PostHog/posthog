import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { todayVerdictLogic } from './todayVerdictLogic'

describe('todayVerdictLogic', () => {
    it.each([
        ['keeps a verdict the API accepts', 200, { a: 'done' }],
        ['takes back a verdict the API refuses', 409, {}],
    ])('%s', async (_, status, finalOverrides) => {
        useMocks({
            post: { '/api/projects/:team_id/signals/reports/:id/state/': () => [status, { detail: 'Refused.' }] },
        })
        initKeaTests()
        const logic = todayVerdictLogic()
        logic.mount()

        logic.actions.requestReportVerdict(
            { reportId: 'a', title: 'Signup form rejects emails', hasOpenPullRequest: false },
            'resolve',
            'briefing'
        )
        expect(logic.values.reportStateOverrides).toEqual({ a: 'done' })

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ reportStateOverrides: finalOverrides })
    })
})
