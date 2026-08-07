import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { sdkHealthLogic } from './sdkHealthLogic'

const MOCK_REPORT: any = {
    overall_health: 'healthy',
    health: 'success',
    needs_updating_count: 0,
    team_sdk_count: 1,
    sdks: [],
}

describe('sdkHealthLogic', () => {
    let logic: ReturnType<typeof sdkHealthLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = sdkHealthLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('surfaces the load error instead of swallowing it', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadReportFailure('SDK scan timed out')
        }).toMatchValues({
            reportError: 'SDK scan timed out',
            report: null,
            // No report to fall back on, so this is a hard error.
            hasErrors: true,
        })
    })

    it('keeps showing the last report when a refresh fails', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadReportSuccess(MOCK_REPORT)
            logic.actions.loadReportFailure('SDK scan timed out')
        }).toMatchValues({
            report: MOCK_REPORT,
            reportError: 'SDK scan timed out',
            // Data is still on screen, so the failed retry must not blank the page.
            hasErrors: false,
        })
    })
})
