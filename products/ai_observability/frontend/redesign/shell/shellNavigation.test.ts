import { urls } from 'scenes/urls'

import {
    SHELL_TABS,
    ShellLocation,
    listPageLinkParams,
    shellDocsUrl,
    shellLinkParams,
    shellLocationForSceneKey,
} from './shellNavigation'

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

    it.each<[string, (params: Record<string, string>) => Record<string, string>, Record<string, string>]>([
        ['tab and scope links keep the filters', shellLinkParams, { date_from: '-7d', view: 'new' }],
        [
            'links between a list and a full page also keep the list scope, order and search',
            listPageLinkParams,
            {
                date_from: '-7d',
                view: 'new',
                person: 'p',
                error: 'e',
                tool: 't',
                order: 'users',
                error_search: 'timeout',
                tool_search: 'search',
            },
        ],
    ])('%s but not the open trace or session', (_name, linkParams, expected) => {
        expect(
            linkParams({
                date_from: '-7d',
                view: 'new',
                order: 'users',
                error_search: 'timeout',
                tool_search: 'search',
                person: 'p',
                error: 'e',
                tool: 't',
                trace: 't1',
                ts: '2026-09-01T10:00:00Z',
                step: 's1',
                session: 'x',
                timestamp: '2026-09-01T09:00:00Z',
            })
        ).toEqual(expected)
    })
})
