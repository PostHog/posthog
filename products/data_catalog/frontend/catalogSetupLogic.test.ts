import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import type { PhaiViewMode } from '~/layout/ai/aiPanelIds'
import { aiShellLogic } from '~/layout/ai/aiShellLogic'
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

    test.each<[string, boolean, PhaiViewMode, boolean]>([
        ['the sandbox runtime is on', true, 'new', true],
        ['the person switched back to the legacy chat, which cannot load the setup skill', true, 'legacy', false],
        ['the sandbox runtime is off, so PostHog AI is the legacy chat', false, 'new', false],
    ])('when %s, postHogAISetupAvailable is correct', (_, sandboxOn, viewMode, expected) => {
        featureFlagLogic.actions.setFeatureFlags(
            sandboxOn ? [FEATURE_FLAGS.PHAI_SANDBOX_MODE] : [],
            sandboxOn ? { [FEATURE_FLAGS.PHAI_SANDBOX_MODE]: true } : {}
        )
        aiShellLogic.mount()
        aiShellLogic.actions.setPhaiViewMode(viewMode)
        const logic = catalogSetupLogic()
        logic.mount()

        expect(logic.values.postHogAISetupAvailable).toBe(expected)
    })

    test('reloads metrics when the person returns to the tab, until an external agent adds one', () => {
        const logic = catalogSetupLogic()
        logic.mount()
        metricsLogic.actions.loadMetricsSuccess([])
        logic.actions.watchForNewMetrics()
        const listCalls = (): number => jest.mocked(dataCatalogMetricsList).mock.calls.length

        const beforeFocus = listCalls()
        window.dispatchEvent(new Event('focus'))
        expect(listCalls()).toBe(beforeFocus + 1)

        metricsLogic.actions.loadMetricsSuccess(metrics(2))
        const afterArrival = listCalls()
        window.dispatchEvent(new Event('focus'))
        expect(listCalls()).toBe(afterArrival)
    })

    test.each([
        ['an SSO reauthentication interrupted the click', ['remember'], 1],
        ['the approval already started setup', ['remember', 'start'], 1],
        ['nothing was clicked', [], 0],
    ])('when %s, setup starts the right number of times', (_, steps, expectedStarts) => {
        const capture = jest.spyOn(posthog, 'capture')
        const logic = catalogSetupLogic()
        logic.mount()
        if (steps.includes('remember')) {
            logic.actions.rememberSetupIntent('banner')
        }
        if (steps.includes('start')) {
            logic.actions.startSetupWithPostHogAI('banner')
        }
        // Resuming twice: the intent is consumed, so setup never starts a second time.
        logic.actions.resumeSetupIntent()
        logic.actions.resumeSetupIntent()

        const starts = capture.mock.calls.filter(([event]) => event === 'data catalog setup with ai started')
        expect(starts).toHaveLength(expectedStarts)
    })
})
