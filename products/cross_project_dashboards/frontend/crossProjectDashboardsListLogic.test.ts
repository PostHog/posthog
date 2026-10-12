import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
        ;(crossProjectDashboardsList as jest.Mock).mockReset()
        ;(crossProjectDashboardsList as jest.Mock).mockResolvedValue({ results: [] })
        ;(crossProjectDashboardsCreate as jest.Mock).mockRejectedValue({ detail: 'Name is too long.' })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.CROSS_PROJECT_DASHBOARDS]: true })
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

    it('does not request the list when the flag is off', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        const logic = crossProjectDashboardsListLogic()

        await expectLogic(logic, () => {
            logic.mount()
        }).toDispatchActions(['loadDashboardsSuccess'])

        expect(crossProjectDashboardsList).not.toHaveBeenCalled()
        logic.unmount()
    })

    it('loads an empty list instead of failing when the API refuses the flag', async () => {
        ;(crossProjectDashboardsList as jest.Mock).mockRejectedValue({ status: 403, code: 'feature_flag_required' })
        const logic = crossProjectDashboardsListLogic()

        await expectLogic(logic, () => {
            logic.mount()
        })
            .toDispatchActions(['loadDashboardsSuccess'])
            .toNotHaveDispatchedActions(['loadDashboardsFailure'])

        expect(logic.values.dashboards).toEqual([])
        logic.unmount()
    })
})
