import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { dataCatalogMetricsList } from './generated/api'
import type { DataCatalogMetricApi } from './generated/api.schemas'
import { METRICS_INTRO_SEEN_KEY, MetricsNotice, metricsIntroLogic } from './metricsIntroLogic'
import { metricsLogic } from './metricsLogic'

jest.mock('./generated/api', () => ({
    dataCatalogMetricsList: jest.fn(),
}))

function metrics(count: number): DataCatalogMetricApi[] {
    return Array.from({ length: count }, (_, index) => ({ name: `metric_${index}` }) as DataCatalogMetricApi)
}

type Step = 'user not loaded' | 'seen earlier' | 'diagram shown' | 'strip shown' | 'server records seen' | 'dismissed'

function seenUser(): typeof MOCK_DEFAULT_USER {
    return { ...MOCK_DEFAULT_USER, has_seen_product_intro_for: { [METRICS_INTRO_SEEN_KEY]: true } }
}

describe('metricsIntroLogic', () => {
    beforeEach(() => {
        initKeaTests()
        // Keep the lazy metrics load pending, so each case sets the loaded catalog through loadMetricsSuccess.
        jest.mocked(dataCatalogMetricsList).mockReturnValue(new Promise(() => {}))
    })

    test.each<[string, number | null, Step[], MetricsNotice]>([
        ['metrics have not loaded yet', null, [], null],
        ['the catalog is empty, which the empty-state diagram covers', 0, [], null],
        ['the user record has not loaded, so a returning person would look new', 3, ['user not loaded'], null],
        ['this is the first visit', 3, [], 'intro'],
        ['the person saw the intro on an earlier visit', 3, ['seen earlier'], 'setup'],
        [
            'the server recorded this visit as seen, which must not hide the intro mid-visit',
            3,
            ['strip shown', 'server records seen'],
            'intro',
        ],
        [
            'the person closed the intro, which must not put the setup offer in its place',
            3,
            ['strip shown', 'dismissed'],
            null,
        ],
        [
            'metrics arrive after the empty-state diagram, which already explained them',
            3,
            ['diagram shown', 'server records seen'],
            'setup',
        ],
    ])('when %s, metricsNotice is correct', (_, metricCount, steps, expected) => {
        // The test app context preloads a user, so "not loaded" has to clear it.
        userLogic.actions.loadUserSuccess(
            steps.includes('user not loaded') ? null : steps.includes('seen earlier') ? seenUser() : MOCK_DEFAULT_USER
        )
        const logic = metricsIntroLogic()
        logic.mount()
        if (steps.includes('diagram shown')) {
            metricsLogic.actions.loadMetricsSuccess([])
            logic.actions.reportIntroShown('empty_state')
        }
        if (metricCount !== null) {
            metricsLogic.actions.loadMetricsSuccess(metrics(metricCount))
        }
        if (steps.includes('strip shown')) {
            logic.actions.reportIntroShown('strip')
        }
        if (steps.includes('server records seen')) {
            userLogic.actions.loadUserSuccess(seenUser())
        }
        if (steps.includes('dismissed')) {
            logic.actions.dismissIntro()
        }

        expect(logic.values.metricsNotice).toBe(expected)
    })
})
