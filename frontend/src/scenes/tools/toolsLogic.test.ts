import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { toolsLogic } from './toolsLogic'

describe('toolsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
    })

    test.each([
        [true, true, false],
        [true, false, true],
        [false, false, true],
    ])('with the rail %s and the warehouse flag %s, lists the warehouse tools: %s', (railOn, warehouseOn, listed) => {
        featureFlagLogic.actions.setFeatureFlags(
            [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.TODAY_RAIL_WAREHOUSE, FEATURE_FLAGS.SQL_EDITOR_BI_MODE],
            {
                [FEATURE_FLAGS.TODAY_RAIL_NAV]: railOn,
                [FEATURE_FLAGS.TODAY_RAIL_WAREHOUSE]: warehouseOn,
                [FEATURE_FLAGS.SQL_EDITOR_BI_MODE]: true,
            }
        )
        const logic = toolsLogic()
        logic.mount()

        const hrefs = logic.values.tools.map((tool) => tool.href?.split(/[?#]/)[0])
        expect(hrefs.includes(urls.sqlEditor())).toBe(listed)
        expect(hrefs.includes(urls.sources())).toBe(listed)
        expect(hrefs.includes(urls.propertyDefinitions())).toBe(listed)
        expect(hrefs.includes(urls.businessIntelligence().split(/[?#]/)[0])).toBe(true)
        expect(hrefs.includes(urls.endpoints())).toBe(true)
        expect(hrefs.length).toBeGreaterThan(0)
    })
})
