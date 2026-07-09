// This test deliberately crosses the toolbar/app boundary: it exists to catch the toolbar's
// duplicated url helpers drifting from the app's real routes (e.g. a product manifest changing
// its path shape), which would break every "open in PostHog" link the toolbar renders.
import { urls as appUrls } from 'scenes/urls'

import { urls as toolbarUrls } from '~/toolbar/urls'

describe('toolbar urls duplicate', () => {
    // Every helper in ~/toolbar/urls needs sample args here — the completeness test enforces it.
    const samples: Record<keyof typeof toolbarUrls, unknown[][]> = {
        action: [[123], ['abc-def']],
        actions: [[]],
        experiment: [[42], ['new'], [42, 'edit'], [7, null, { name: 'my experiment' }]],
        experiments: [[]],
        featureFlag: [[123], ['my-flag']],
        featureFlags: [[], ['history']],
        productTour: [['tour-id'], ['tour-id', 'step=2'], ['tour-id', '?step=2']],
        sessionProfile: [['session-uuid']],
        settings: [[], ['project'], ['environment-customization', 'date-and-time'], ['user']],
        survey: [['survey-uuid'], ['new']],
        surveys: [[], ['archived']],
        webAnalyticsWebVitals: [[]],
    }

    it.each(Object.keys(toolbarUrls) as (keyof typeof toolbarUrls)[])('%s matches the app implementation', (helper) => {
        const argSets = samples[helper]
        expect(argSets.length).toBeGreaterThan(0)
        for (const args of argSets) {
            const toolbarResult = (toolbarUrls[helper] as (...a: unknown[]) => string)(...args)
            const appResult = (appUrls[helper] as (...a: unknown[]) => string)(...args)
            expect(toolbarResult).toBe(appResult)
        }
    })
})
