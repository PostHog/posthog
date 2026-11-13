import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { dataCatalogMetricsList } from './generated/api'
import type { DataCatalogMetricApi } from './generated/api.schemas'
import { METRICS_INTRO_SEEN_KEY, metricsIntroLogic } from './metricsIntroLogic'
import { metricsLogic } from './metricsLogic'

jest.mock('./generated/api', () => ({
    dataCatalogMetricsList: jest.fn(),
}))

function metrics(count: number): DataCatalogMetricApi[] {
    return Array.from({ length: count }, (_, index) => ({ name: `metric_${index}` }) as DataCatalogMetricApi)
}

function setSeenOnServer(): void {
    userLogic.actions.loadUserSuccess({
        ...MOCK_DEFAULT_USER,
        has_seen_product_intro_for: { [METRICS_INTRO_SEEN_KEY]: true },
    })
}

describe('metricsIntroLogic', () => {
    beforeEach(() => {
        initKeaTests()
        // Keep the lazy metrics load pending, so each case sets the loaded catalog through loadMetricsSuccess.
        jest.mocked(dataCatalogMetricsList).mockReturnValue(new Promise(() => {}))
    })

    test.each([
        ['metrics have not loaded yet', null, 'never', false],
        ['the catalog is empty, which the empty-state diagram covers', 0, 'never', false],
        ['this is the first visit', 3, 'never', true],
        ['the person saw the intro on an earlier visit', 3, 'earlier visit', false],
        ['the server recorded this visit as seen, which must not hide it mid-visit', 3, 'this visit', true],
        ['the person dismissed it', 3, 'dismissed', false],
    ])('when %s, showIntroStrip is correct', (_, metricCount, seen, expected) => {
        if (seen === 'earlier visit') {
            setSeenOnServer()
        }
        const logic = metricsIntroLogic()
        logic.mount()
        if (metricCount !== null) {
            metricsLogic.actions.loadMetricsSuccess(metrics(metricCount))
        }
        if (seen === 'this visit') {
            logic.actions.reportIntroShown('strip')
            setSeenOnServer()
        }
        if (seen === 'dismissed') {
            logic.actions.reportIntroShown('strip')
            logic.actions.dismissIntro()
        }

        expect(logic.values.showIntroStrip).toBe(expected)
    })
})
