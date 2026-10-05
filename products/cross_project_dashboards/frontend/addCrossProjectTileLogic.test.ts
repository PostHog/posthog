import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { organizationLogic } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'

import { addCrossProjectTileLogic } from './addCrossProjectTileLogic'
import { crossProjectDashboardLogic } from './crossProjectDashboardLogic'
import { crossProjectDashboardsRetrieve } from './generated/api'

jest.mock('lib/lemon-ui/LemonDialog', () => ({ LemonDialog: { open: jest.fn() } }))

jest.mock('./generated/api', () => ({
    __esModule: true,
    crossProjectDashboardsRetrieve: jest.fn(),
}))

const mockedDialogOpen = LemonDialog.open as jest.Mock
const mockedRetrieve = crossProjectDashboardsRetrieve as jest.Mock

const DASHBOARD_ID = '01a0f19d-1c44-715a-a679-188869bd033f'

const TILE = { id: 'tile-1', project_id: 53, insight_id: 266, layouts: {}, color: null, filters_overrides: {} }

describe('addCrossProjectTileLogic', () => {
    let dashboardLogic: ReturnType<typeof crossProjectDashboardLogic.build>
    let logic: ReturnType<typeof addCrossProjectTileLogic.build>

    beforeEach(async () => {
        mockedDialogOpen.mockReset()
        mockedRetrieve.mockResolvedValue({ id: DASHBOARD_ID, name: 'Across projects', filters: {}, tiles: [TILE] })
        initKeaTests()
        organizationLogic.mount()
        organizationLogic.actions.loadCurrentOrganizationSuccess({ id: 'org-1', name: 'Org' } as any)
        dashboardLogic = crossProjectDashboardLogic({ id: DASHBOARD_ID })
        dashboardLogic.mount()
        logic = addCrossProjectTileLogic({ dashboardId: DASHBOARD_ID })
        logic.mount()
        await expectLogic(dashboardLogic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
        dashboardLogic.unmount()
    })

    it('asks before an added insight reloads the dashboard over unsaved layout changes', () => {
        dashboardLogic.actions.enterLayoutEdit()
        dashboardLogic.actions.setPendingLayouts({ sm: [{ i: 'tile-1', x: 6, y: 0, w: 6, h: 5 }] })

        logic.actions.requestOpenModal()

        expect(logic.values.isOpen).toBe(false)
        expect(dashboardLogic.values.layoutEditMode).toBe(true)

        mockedDialogOpen.mock.calls[0][0].primaryButton.onClick()

        expect(logic.values.isOpen).toBe(true)
        expect(dashboardLogic.values.layoutEditMode).toBe(false)
    })
})
