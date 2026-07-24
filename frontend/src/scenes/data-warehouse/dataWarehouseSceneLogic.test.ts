import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DataWarehouseTab, dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'

describe('dataWarehouseSceneLogic', () => {
    let logic: ReturnType<typeof dataWarehouseSceneLogic.build>
    let flagsLogic: ReturnType<typeof featureFlagLogic.build>
    let warehouseStatusResponse: [number, Record<string, string>]

    const mountScene = (): void => {
        logic = dataWarehouseSceneLogic()
        logic.mount()
    }

    const waitForWarehouseStatus = async (): Promise<void> => {
        await expectLogic(logic).toDispatchActions(['loadWarehouseStatusSuccess'])
    }

    beforeEach(() => {
        warehouseStatusResponse = [404, {}]
        useMocks({
            get: {
                '/api/projects/:team_id/data_warehouse/warehouse_status/': () => warehouseStatusResponse,
            },
        })
        initKeaTests()
        flagsLogic = featureFlagLogic()
        flagsLogic.mount()
        flagsLogic.actions.setFeatureFlags([FEATURE_FLAGS.DATA_WAREHOUSE_SCENE], {
            [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]: true,
        })
    })

    afterEach(() => {
        logic?.unmount()
        flagsLogic.unmount()
    })

    // Overview has nothing to report until a warehouse is actually serving. Until then the scene has
    // to collapse to Settings alone, which is what renders the setup form (with no tab bar).
    it.each([
        { name: 'no warehouse provisioned', status: null, expectedTabs: [DataWarehouseTab.SETTINGS] },
        {
            name: 'warehouse still provisioning',
            status: { state: 'provisioning' },
            expectedTabs: [DataWarehouseTab.SETTINGS],
        },
        {
            name: 'warehouse ready',
            status: { state: 'ready' },
            expectedTabs: [DataWarehouseTab.OVERVIEW, DataWarehouseTab.SETTINGS],
        },
    ])('$name', async ({ status, expectedTabs }) => {
        warehouseStatusResponse = status ? [200, status] : [404, {}]
        mountScene()
        await waitForWarehouseStatus()

        expect(logic.values.availableTabs).toEqual(expectedTabs)
        expect(logic.values.activeTab).toBe(expectedTabs[0])
    })

    it('leaves the tab set unresolved until the warehouse status lands', () => {
        warehouseStatusResponse = [200, { state: 'ready' }]
        mountScene()

        expect(logic.values.warehouseStatusResolved).toBe(false)
    })

    // The URL is parsed before the warehouse status arrives, so a requested tab has to survive the
    // wait — clamping it against a tab list that doesn't include Overview yet would drop it.
    it.each([[DataWarehouseTab.OVERVIEW], [DataWarehouseTab.SETTINGS]])(
        'honors a tab requested before the warehouse status resolves (%s)',
        async (tab) => {
            warehouseStatusResponse = [200, { state: 'ready' }]
            mountScene()
            router.actions.push(urls.dataOps(tab))
            await waitForWarehouseStatus()

            expect(logic.values.activeTab).toBe(tab)
        }
    )
})
