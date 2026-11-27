import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { dashboardSceneLogic } from './dashboardSceneLogic'

describe('dashboardSceneLogic', () => {
    let logic: ReturnType<typeof dashboardSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT!,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT!.resource_access_control,
                [AccessControlResourceType.Dashboard]: AccessControlLevel.Editor,
            },
        }
        logic = dashboardSceneLogic({})
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('keeps the shown tab when tabs are reordered, and shows a tab once it is added', () => {
        const shown = logic.values.activeTab!.id
        logic.actions.applyDashboardEdit({ edit: 'moveTab', id: shown, before: null })

        expect(logic.values.dashboard!.tabs.at(-1)!.id).toBe(shown)
        expect(logic.values.activeTab!.id).toBe(shown)

        logic.actions.applyDashboardEdit({ edit: 'addTab', title: 'New tab' })

        expect(logic.values.activeTab!.title).toBe('New tab')
    })

    it('keeps the tab asked for in the URL while the board loads', async () => {
        const spec = { version: 2, title: 'Board', tabs: [{ id: 'main', title: 'Main', tiles: [] }] }
        useMocks({
            get: {
                '/api/projects/:team_id/dashboard_v2/boards/:uid/': () => ({
                    uid: 'b1',
                    version: 1,
                    managed_by: 'native',
                    spec,
                }),
            },
        })
        logic.unmount()
        router.actions.push('/dashboard-v2/b1', { tab: 'main' })
        logic = dashboardSceneLogic({ uid: 'b1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(router.values.searchParams.tab).toBe('main')
    })
})
