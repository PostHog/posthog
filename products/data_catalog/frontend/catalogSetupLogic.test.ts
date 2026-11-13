import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import {
    SETUP_BANNER_DISMISSED_KEY,
    SETUP_STARTED_KEY,
    SMALL_CATALOG_SIZE,
    catalogSetupLogic,
} from './catalogSetupLogic'
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
        ['metrics have not loaded yet', null, null, false],
        ['the catalog is empty, which the empty state covers', 0, null, false],
        ['the catalog is small', 3, null, true],
        ['the catalog has reached the small-catalog size', SMALL_CATALOG_SIZE, null, false],
        ['the user dismissed the banner before', 3, SETUP_BANNER_DISMISSED_KEY, false],
        [
            'the user started setup before, which can propose fewer metrics than the threshold',
            3,
            SETUP_STARTED_KEY,
            false,
        ],
        ['the user record has not loaded, so an earlier dismissal is unknown', 3, 'user not loaded', false],
    ])('when %s, showSetupBanner is correct', (_, metricCount, seenKey, expected) => {
        if (seenKey === 'user not loaded') {
            // The test app context preloads a user, so "not loaded" has to clear it.
            userLogic.actions.loadUserSuccess(null)
        } else if (seenKey) {
            userLogic.actions.loadUserSuccess({
                ...MOCK_DEFAULT_USER,
                has_seen_product_intro_for: { [seenKey]: true },
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
