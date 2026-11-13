import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { SETUP_BANNER_DISMISSED_KEY, SMALL_CATALOG_SIZE, catalogSetupLogic } from './catalogSetupLogic'
import { dataCatalogMetricsList } from './generated/api'
import type { DataCatalogMetricApi } from './generated/api.schemas'
import { metricsLogic } from './metricsLogic'

jest.mock('./generated/api', () => ({
    dataCatalogMetricsList: jest.fn(),
}))

function metrics(count: number): DataCatalogMetricApi[] {
    return Array.from({ length: count }, (_, index) => ({ name: `metric_${index}` }) as DataCatalogMetricApi)
}

describe('catalogSetupLogic', () => {
    beforeEach(() => {
        initKeaTests()
        // The banner selector reads the lazy metrics loader. Keep that load pending, so each case
        // controls the loaded catalog through loadMetricsSuccess alone.
        jest.mocked(dataCatalogMetricsList).mockReturnValue(new Promise(() => {}))
    })

    test.each([
        ['metrics have not loaded yet', null, false, false],
        ['the catalog is empty, which the empty state covers', 0, false, false],
        ['the catalog is small', 3, false, true],
        ['the catalog has reached the small-catalog size', SMALL_CATALOG_SIZE, false, false],
        ['the user dismissed the banner before', 3, true, false],
    ])('when %s, showSetupBanner is correct', (_, metricCount, dismissedBefore, expected) => {
        if (dismissedBefore) {
            userLogic.actions.loadUserSuccess({
                ...MOCK_DEFAULT_USER,
                has_seen_product_intro_for: { [SETUP_BANNER_DISMISSED_KEY]: true },
            })
        }
        const logic = catalogSetupLogic()
        logic.mount()
        if (metricCount !== null) {
            metricsLogic.actions.loadMetricsSuccess(metrics(metricCount))
        }

        expect(logic.values.showSetupBanner).toBe(expected)
    })
})
