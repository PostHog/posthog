import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import * as generatedApi from '../generated/api'
import { dashboardsSetupLogic } from './dashboardsSetupLogic'

// Guards the mapping into the app-wide setup-status layer: if it breaks, the scene
// empty-state gate strands on its spinner or shows the wrong surface.
describe('dashboardsSetupLogic', () => {
    let listSpy: jest.SpyInstance

    beforeEach(() => {
        listSpy = jest.spyOn(generatedApi, 'dashboardsList')
        initKeaTests()
    })

    afterEach(() => {
        listSpy.mockRestore()
    })

    it.each([
        [0, 'needs-setup'],
        [1, 'has-data'],
        [17, 'has-data'],
    ])('pushes a dashboard count of %i as status %s', async (count, expected) => {
        listSpy.mockResolvedValue({ count, results: [] })
        const logic = dashboardsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.DASHBOARDS }).values.status).toBe(expected)
    })

    it('re-detects when a dashboard is created without leaving the scene', async () => {
        listSpy.mockResolvedValueOnce({ count: 0, results: [] }).mockResolvedValue({ count: 1, results: [] })
        const logic = dashboardsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.DASHBOARDS }).values.status).toBe('needs-setup')

        // Creating from the empty state's modal does not navigate unless the user opts in,
        // so without the recheck wiring the gate would keep hiding the new dashboard.
        dashboardsModel.actions.addDashboardSuccess({ id: 1, name: 'First' } as any)
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.DASHBOARDS }).values.status).toBe('has-data')
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        listSpy.mockRejectedValue(new Error('network down'))
        const logic = dashboardsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.DASHBOARDS }).values.status).toBe('unknown')
    })
})
