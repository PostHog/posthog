import { urls } from 'scenes/urls'

import { SHELL_TABS, ShellLocation, shellDocsUrl, shellLocationForSceneKey } from './shellNavigation'

const DOCS = 'https://posthog.com/docs/ai-observability'

describe('shellNavigation', () => {
    it.each<[string | null, ShellLocation]>([
        ['aiObservabilityDashboard', { tab: 'home', scope: null }],
        ['aiObservabilityTraces', { tab: 'activity', scope: 'traces' }],
        ['aiObservabilitySessions', { tab: 'activity', scope: 'sessions' }],
        ['aiObservabilityErrors', { tab: 'diagnostics', scope: 'errors' }],
        ['aiObservabilityTools', { tab: 'diagnostics', scope: 'tools' }],
        ['aiObservabilityUsers', { tab: 'people', scope: null }],
        ['aiObservabilityGenerations', { tab: null, scope: null }],
        ['aiObservabilityReviews', { tab: null, scope: null }],
        ['aiObservabilitySelfDriving', { tab: null, scope: null }],
        ['aiObservabilitySentiment', { tab: null, scope: null }],
        ['constructor', { tab: null, scope: null }],
        [null, { tab: null, scope: null }],
    ])('places the route %s', (sceneKey, expected) => {
        expect(shellLocationForSceneKey(sceneKey)).toEqual(expected)
    })

    it('sends each tab link to its default scope', () => {
        expect(SHELL_TABS.map((tab) => [tab.id, tab.path])).toEqual([
            ['home', urls.aiObservabilityDashboard()],
            ['activity', urls.aiObservabilityTraces()],
            ['diagnostics', urls.aiObservabilityErrors()],
            ['people', urls.aiObservabilityUsers()],
        ])
    })

    it('lists the scopes of each tab in display order', () => {
        expect(SHELL_TABS.map((tab) => tab.scopes.map((scope) => [scope.id, scope.path]))).toEqual([
            [],
            [
                ['sessions', urls.aiObservabilitySessions()],
                ['traces', urls.aiObservabilityTraces()],
            ],
            [
                ['errors', urls.aiObservabilityErrors()],
                ['tools', urls.aiObservabilityTools()],
            ],
            [],
        ])
    })

    it.each<[ShellLocation, string]>([
        [{ tab: 'activity', scope: 'sessions' }, `${DOCS}/sessions`],
        [{ tab: 'activity', scope: 'traces' }, `${DOCS}/traces`],
        [{ tab: 'diagnostics', scope: 'errors' }, `${DOCS}/errors`],
        [{ tab: 'diagnostics', scope: 'tools' }, `${DOCS}/tools`],
        [{ tab: 'home', scope: null }, `${DOCS}/installation`],
        [{ tab: 'people', scope: null }, `${DOCS}/installation`],
        [{ tab: null, scope: null }, `${DOCS}/installation`],
    ])('links %j to its docs page', (location, expected) => {
        expect(shellDocsUrl(location)).toBe(expected)
    })
})
