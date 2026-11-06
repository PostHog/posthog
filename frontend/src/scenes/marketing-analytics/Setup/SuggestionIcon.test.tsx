import { cleanup, render, waitFor } from '@testing-library/react'

import type { Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SuggestionIcon } from './SuggestionIcon'

const suggestion = (overrides: Partial<Suggestion> = {}): Suggestion =>
    ({
        id: 'fix_sync:google_ads',
        kind: 'fix_sync',
        source: 'deterministic',
        severity: 'error',
        title: 'Retry the Google Ads sync',
        evidence: 'Last sync is 3 days old.',
        unlocks: [],
        apply: null,
        also_recommended: [],
        safe_to_batch: false,
        rank_score: 10,
        integration: 'GoogleAds',
        deep_link: null,
        docs_url: null,
        spend_at_risk: 0,
        event_volume: 0,
        ...overrides,
    }) as Suggestion

/** Scoped to one render's container: this repo has no RTL auto-cleanup, so a
 * document-wide query picks up every earlier render in the file. */
function slotIn(container: HTMLElement): HTMLElement {
    const found = container.querySelector<HTMLElement>('[data-attr="suggestion-icon"]')
    if (!found) {
        throw new Error('no suggestion icon rendered')
    }
    return found
}

describe('SuggestionIcon', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/wizard': () => [
                    200,
                    { GoogleAds: { name: 'GoogleAds', iconPath: '/static/services/google-ads.png' } },
                ],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('reserves the same width whether or not a logo resolves', async () => {
        // The point of the fixed slot: a ranked list must not indent each row
        // differently depending on whether its platform happened to resolve a logo,
        // and must not re-flow when one 404s.
        const withLogo = render(<SuggestionIcon suggestion={suggestion()} />)
        await waitFor(() => expect(slotIn(withLogo.container).querySelector('img')).toBeTruthy())

        const withoutLogo = render(<SuggestionIcon suggestion={suggestion({ integration: null })} />)

        // Same class list on both, so the width can't drift between the two branches
        // without this failing — which is the whole invariant.
        expect(slotIn(withoutLogo.container).className).toBe(slotIn(withLogo.container).className)
        expect(slotIn(withLogo.container).className).toContain('size-[30px]')
    })

    it('falls back to the severity glyph when there is no platform', () => {
        // A collapsed group, a conversion goal, traffic untagged everywhere: nothing to
        // put a logo on, so severity has to carry the slot on its own.
        const { container } = render(<SuggestionIcon suggestion={suggestion({ integration: null })} />)

        expect(slotIn(container).querySelector('img')).toBeNull()
        expect(slotIn(container).querySelector('svg')).toBeTruthy()
    })

    it('falls back when the platform is absent from the source catalogue', async () => {
        // `availableSources` is also null when the wizard endpoint 403s, and SourceIcon
        // renders an indefinite skeleton in that state rather than giving up — which is
        // why `usePlatformLogo` checks the catalogue itself.
        const { container } = render(<SuggestionIcon suggestion={suggestion({ integration: 'NotARealPlatform' })} />)

        await waitFor(() => expect(slotIn(container).querySelector('svg')).toBeTruthy())
        expect(slotIn(container).querySelector('img')).toBeNull()
    })
})
