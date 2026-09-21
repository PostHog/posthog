import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { SetupSection } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'
import type { Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SuggestionRow } from './SuggestionRow'

const suggestion = (overrides: Partial<Suggestion> = {}): Suggestion =>
    ({
        id: 'fix_sync:bing_ads',
        kind: 'fix_sync',
        source: 'deterministic',
        severity: 'error',
        confidence: 0.9,
        title: 'Fix the Bing Ads sync',
        evidence: 'Last successful sync is older than 24h.',
        unlocks: [],
        apply: null,
        also_recommended: [],
        safe_to_batch: false,
        rank_score: 10,
        integration: 'BingAds',
        deep_link: null,
        docs_url: null,
        spend_at_risk: 0,
        event_volume: 0,
        ...overrides,
    }) as Suggestion

describe('SuggestionRow', () => {
    beforeEach(() => {
        useMocks({ get: { '/api/projects/:team_id/marketing_analytics/utm_audit': () => [200, {}] } })
        initKeaTests()
    })

    afterEach(cleanup)

    /** A suggestion with no `apply` is still actionable — the plan says where the fix
     * lives. Offering only Dismiss is how a real finding reads as a dead end. */
    it('links out when the fix lives outside the tab', async () => {
        const { container } = render(
            <SuggestionRow suggestion={suggestion({ deep_link: '/warehouse/1/schemas' })} onReview={() => {}} />
        )

        await waitFor(() => expect(screen.getByText('Open source')).toBeTruthy())
        // `deep_link` arrives project-relative, and LemonButton scopes it to the current project.
        expect(container.querySelector('a')?.getAttribute('href')).toContain('/warehouse/1/schemas')
    })

    it('offers the owning section when there is no link', async () => {
        render(<SuggestionRow suggestion={suggestion({ kind: 'fix_platform_urls' })} onReview={() => {}} />)

        await waitFor(() => expect(screen.getByText('Integration health')).toBeTruthy())
    })

    /** Setup re-hosts the settings components, so sending someone out to a new tab to
     * reach the same editor is a detour. */
    it('keeps an open_settings fix inside the tab', async () => {
        render(
            <SuggestionRow
                suggestion={
                    {
                        ...suggestion({ kind: 'fix_conversion_goal' }),
                        apply: { op: 'open_settings', anchor: 'environment-marketing-analytics' },
                    } as Suggestion
                }
                onReview={() => {}}
            />
        )

        await waitFor(() => expect(screen.getByText('Conversion goals')).toBeTruthy())
        expect(screen.queryByText('Open settings')).toBeNull()
    })

    it('does not offer the section it is already rendered in', async () => {
        render(
            <SuggestionRow
                suggestion={suggestion({ kind: 'fix_platform_urls' })}
                onReview={() => {}}
                currentSection={SetupSection.INTEGRATION_HEALTH}
            />
        )

        await waitFor(() => expect(screen.getByText('Dismiss')).toBeTruthy())
        expect(screen.queryByText('Integration health')).toBeNull()
    })
})
