import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { openDismissReportDialog } from 'products/signals/frontend/inbox/components/shell/DismissReportDialog'
import { openResolveReportDialog } from 'products/signals/frontend/inbox/components/shell/ResolveReportDialog'

import { todayVerdictLogic } from './todayVerdictLogic'

jest.mock('products/signals/frontend/inbox/components/shell/ResolveReportDialog', () => ({
    openResolveReportDialog: jest.fn(),
}))
jest.mock('products/signals/frontend/inbox/components/shell/DismissReportDialog', () => ({
    openDismissReportDialog: jest.fn(),
}))

describe('todayVerdictLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it.each(['resolve', 'dismiss'] as const)('opens one %s dialog per report until it closes', (verdict) => {
        initKeaTests()
        const logic = todayVerdictLogic()
        logic.mount()
        const target = { reportId: 'a', title: 'Signup form rejects emails', hasOpenPullRequest: false }
        const openDialog = verdict === 'resolve' ? openResolveReportDialog : openDismissReportDialog
        const otherDialog = verdict === 'resolve' ? openDismissReportDialog : openResolveReportDialog

        logic.actions.requestReportVerdict(target, verdict, 'briefing')
        logic.actions.requestReportVerdict(target, verdict, 'briefing')
        logic.actions.requestReportVerdict(target, verdict === 'resolve' ? 'dismiss' : 'resolve', 'report_page')
        expect(openDialog).toHaveBeenCalledTimes(1)
        expect(otherDialog).not.toHaveBeenCalled()

        logic.actions.requestReportVerdict({ ...target, reportId: 'b' }, verdict, 'briefing')
        expect(openDialog).toHaveBeenCalledTimes(2)

        jest.mocked(openDialog).mock.calls[0][0].onAfterClose?.()
        logic.actions.requestReportVerdict(target, verdict, 'briefing')
        expect(openDialog).toHaveBeenCalledTimes(3)
    })

    it.each([
        ['keeps a verdict the API accepts', 200, { a: 'done' }],
        ['takes back a verdict the API refuses', 409, {}],
    ])('%s', async (_, status, finalOverrides) => {
        const stateBodies: unknown[] = []
        let releaseResponse: () => void = () => undefined
        const responseReady = new Promise<void>((resolve) => {
            releaseResponse = resolve
        })
        let responseStatus = status
        useMocks({
            post: {
                '/api/projects/:team_id/signals/reports/:id/state/': async ({ request }) => {
                    stateBodies.push(await request.json())
                    await responseReady
                    return [responseStatus, { detail: 'Refused.' }]
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
        const duplicate = Promise.resolve(dialog.onConfirm({ reason: 'no_action_needed', note: 'Reviewed' })).catch(
            () => undefined
        )
        await waitFor(() => expect(stateBodies).toHaveLength(1))
        releaseResponse()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ reportStateOverrides: finalOverrides })
        await Promise.all([submitted, duplicate])
        expect(stateBodies).toEqual([
            { state: 'resolved', dismissal_reason: 'no_action_needed', dismissal_note: 'Reviewed' },
        ])

        responseStatus = 200
        const repeated = Promise.resolve(dialog.onConfirm({ reason: 'no_action_needed', note: 'Reviewed' }))
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ reportStateOverrides: { a: 'done' } })
        await repeated
        expect(stateBodies).toHaveLength(status === 200 ? 1 : 2)
    })
})
