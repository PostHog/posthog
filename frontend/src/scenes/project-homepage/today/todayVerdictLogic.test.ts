import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { openResolveReportDialog } from 'products/signals/frontend/inbox/components/shell/ResolveReportDialog'

import { todayVerdictLogic } from './todayVerdictLogic'

jest.mock('products/signals/frontend/inbox/components/shell/ResolveReportDialog', () => ({
    openResolveReportDialog: jest.fn(),
}))

describe('todayVerdictLogic', () => {
    it.each([
        ['keeps a verdict the API accepts', 200, { a: 'done' }],
        ['takes back a verdict the API refuses', 409, {}],
    ])('%s', async (_, status, finalOverrides) => {
        const stateBodies: Record<string, unknown>[] = []
        useMocks({
            post: {
                '/api/projects/:team_id/signals/reports/:id/state/': async ({ request }) => {
                    stateBodies.push(await request.json())
                    return [status, { detail: 'Refused.' }]
                },
            },
        })
        initKeaTests()
        const logic = todayVerdictLogic()
        logic.mount()

        logic.actions.requestReportVerdict(
            { reportId: 'a', title: 'Signup form rejects emails', hasOpenPullRequest: false },
            'resolve',
            'briefing'
        )
        expect(logic.values.reportStateOverrides).toEqual({})
        expect(stateBodies).toEqual([])
        const dialog = jest.mocked(openResolveReportDialog).mock.calls.at(-1)![0]
        const submitted = Promise.resolve(dialog.onConfirm({ reason: 'no_action_needed', note: 'Reviewed' })).catch(
            () => undefined
        )

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ reportStateOverrides: finalOverrides })
        await submitted
        expect(stateBodies).toEqual([
            { state: 'resolved', dismissal_reason: 'no_action_needed', dismissal_note: 'Reviewed' },
        ])
    })
})
