import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { osBridgeLogic } from '../bridge/osBridgeLogic'
import { osWindowsLogic } from '../windows/osWindowsLogic'
import { osMenuBarLogic } from './osMenuBarLogic'

describe('osMenuBarLogic', () => {
    let logic: ReturnType<typeof osMenuBarLogic.build>

    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
        useMocks({ get: { '/api/environments/:team_id/user_product_list/': { results: [] } } })
        initKeaTests()
        router.actions.push(`/project/${MOCK_TEAM_ID}${urls.os()}`)
        logic = osMenuBarLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('follows the focused window, and opens a picked page in that window', async () => {
        expect(logic.values.appMenu).toBeNull()

        osWindowsLogic.actions.openWindow(urls.surveys())
        osWindowsLogic.actions.openWindow(urls.savedInsights())
        const insights = osWindowsLogic.values.focusedWindow?.id as string
        expect(logic.values.appMenu?.app.name).toEqual('Product analytics')

        await expectLogic(logic, () => logic.actions.openAppPage(urls.alerts())).toDispatchActions(osBridgeLogic, [
            osBridgeLogic.actionCreators.navigateWindow(insights, urls.alerts()),
        ])

        osWindowsLogic.actions.minimizeWindow(insights)
        expect(logic.values.appMenu?.app.name).toEqual('Surveys')

        osWindowsLogic.actions.minimizeWindow(osWindowsLogic.values.focusedWindow?.id as string)
        expect(logic.values.appMenu).toBeNull()
    })
})
