import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { sidePanelActivityLogic, SidePanelActivityTab } from './sidePanelActivityLogic'

jest.mock('lib/components/ActivityLog/activityLogLogic', () => ({
    ...jest.requireActual('lib/components/ActivityLog/activityLogLogic'),
    ensureActivityDescribersLoaded: jest.fn().mockResolvedValue(undefined),
}))

function setActivityLogAccess(level: AccessControlLevel): void {
    window.POSTHOG_APP_CONTEXT = {
        resource_access_control: {
            [AccessControlResourceType.ActivityLog]: level,
        },
    } as unknown as AppContext
}

describe('sidePanelActivityLogic', () => {
    let logic: ReturnType<typeof sidePanelActivityLogic.build>
    let listSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        listSpy = jest.spyOn(api.activity, 'list').mockResolvedValue({ results: [], next: null })
    })

    afterEach(() => {
        logic?.unmount()
        listSpy.mockRestore()
        delete window.POSTHOG_APP_CONTEXT
    })

    it('does not request activity when the user lacks viewer access', async () => {
        setActivityLogAccess(AccessControlLevel.None)
        logic = sidePanelActivityLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setActiveTab(SidePanelActivityTab.All)
            logic.actions.loadAllActivity()
        }).toFinishAllListeners()

        expect(listSpy).not.toHaveBeenCalled()
        expect(logic.values.allActivityResponse).toBeNull()
    })

    it('requests activity when the user has viewer access', async () => {
        setActivityLogAccess(AccessControlLevel.Viewer)
        logic = sidePanelActivityLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadAllActivity()
        }).toFinishAllListeners()

        expect(listSpy).toHaveBeenCalled()
    })
})
