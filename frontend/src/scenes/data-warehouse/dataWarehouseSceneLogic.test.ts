import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { DataWarehouseTab, dataWarehouseSceneLogic } from './dataWarehouseSceneLogic'

describe('dataWarehouseSceneLogic', () => {
    let logic: ReturnType<typeof dataWarehouseSceneLogic.build>
    let flagsLogic: ReturnType<typeof featureFlagLogic.build>

    beforeEach(() => {
        initKeaTests()
        flagsLogic = featureFlagLogic()
        flagsLogic.mount()
        logic = dataWarehouseSceneLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        flagsLogic.unmount()
    })

    it('uses data-warehouse-scene to expose the managed warehouse settings tab', async () => {
        await expectLogic(flagsLogic, () => {
            flagsLogic.actions.setFeatureFlags([FEATURE_FLAGS.DATA_WAREHOUSE_SCENE], {
                [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]: true,
            })
        })

        expect(logic.values.availableTabs).toEqual([DataWarehouseTab.SETTINGS])
    })
})
