import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'

import { initKeaTests } from '~/test/init'

import { crossProjectDashboardsListLogic } from './crossProjectDashboardsListLogic'
import { crossProjectDashboardsCreate, crossProjectDashboardsList } from './generated/api'

jest.mock('./generated/api', () => ({
    __esModule: true,
    crossProjectDashboardsList: jest.fn(),
    crossProjectDashboardsCreate: jest.fn(),
}))

describe('crossProjectDashboardsListLogic', () => {
    beforeEach(() => {
        ;(crossProjectDashboardsList as jest.Mock).mockResolvedValue({ results: [] })
        ;(crossProjectDashboardsCreate as jest.Mock).mockRejectedValue({ detail: 'Name is too long.' })
        initKeaTests()
        organizationLogic.mount()
        organizationLogic.actions.loadCurrentOrganizationSuccess({ id: 'org-1', name: 'Org' } as any)
    })

    it('keeps the modal open with the typed name when creating fails, so the user can retry', async () => {
        const logic = crossProjectDashboardsListLogic()
        logic.mount()
        logic.actions.openNewModal()
        logic.actions.setNewName('Quarterly overview')

        logic.actions.createDashboard()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.isNewModalOpen).toBe(true)
        expect(logic.values.newName).toBe('Quarterly overview')
        expect(logic.values.isCreating).toBe(false)
        logic.unmount()
    })
})
