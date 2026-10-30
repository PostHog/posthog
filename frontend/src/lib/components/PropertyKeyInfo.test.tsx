import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { PropertyKeyInfo } from './PropertyKeyInfo'
import { TaxonomicFilterGroupType } from './TaxonomicFilter/types'

describe('PropertyKeyInfo', () => {
    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    function renderSessionDuration(onWrapperClick = jest.fn()): { name: HTMLElement; overlayText: HTMLElement } {
        render(
            <button type="button" onClick={onWrapperClick}>
                <PropertyKeyInfo value="$session_duration" type={TaxonomicFilterGroupType.SessionProperties} />
            </button>
        )
        const name = screen.getByLabelText('Session duration')
        fireEvent.mouseEnter(name)
        return { name, overlayText: screen.getByText(/Learn more about how PostHog tracks sessions/) }
    }

    it('keeps the overlay open when the pointer moves from the name into it', () => {
        jest.useFakeTimers()
        const { name, overlayText } = renderSessionDuration()

        fireEvent.mouseOut(name, { relatedTarget: overlayText })
        act(() => {
            jest.runOnlyPendingTimers()
        })

        expect(overlayText).toBeInTheDocument()

        // Unmount and flush under fake timers, or React's scheduler waits for a timer that never fires,
        // and later lazy components in this file never resolve.
        cleanup()
        act(() => {
            jest.runOnlyPendingTimers()
        })
    })

    it('does not run the onClick of a wrapping element when the overlay is clicked', () => {
        const onWrapperClick = jest.fn()
        const { overlayText } = renderSessionDuration(onWrapperClick)

        fireEvent.click(overlayText)

        expect(onWrapperClick).not.toHaveBeenCalled()
    })

    test.each([
        [
            'shows Archived rather than Disabled for an archived flag',
            [{ key: 'my-flag', active: false, archived: true, filters: { groups: [] } }],
            ['Archived', 'Release conditions'],
            ['Disabled'],
        ],
        [
            'hides conditions and variants for a flag config it cannot read',
            [{ key: 'my-flag', active: true, archived: false, filters: { version: 2, rules: [] } }],
            ['Enabled'],
            ['Release conditions', 'Variants'],
        ],
        ['says so when no flag has the key', [], ['No flag with this key in this project'], ['Status']],
        [
            'says the lookup failed when the request fails',
            null,
            ['Could not load this flag. Try again in a moment.'],
            ['No flag with this key in this project'],
        ],
    ])('flag overview %s', async (_name, flags, shown, hidden) => {
        useMocks({
            get: {
                '/api/projects/:team_id/feature_flags/': ({ request }) => {
                    if (!flags) {
                        return [500, {}]
                    }
                    const wantsArchived = new URL(request.url).searchParams.get('archived') === 'true'
                    const results = flags.filter((flag) => flag.archived === wantsArchived)
                    return [200, { count: results.length, results }]
                },
            },
        })
        initKeaTests()
        render(<PropertyKeyInfo value="$feature/my-flag" type={TaxonomicFilterGroupType.EventProperties} />)
        fireEvent.mouseEnter(screen.getByLabelText('Feature: my-flag'))

        expect(await screen.findByText(shown[0], {}, { timeout: 3000 })).toBeInTheDocument()
        for (const text of [...shown, ...hidden]) {
            expect(!!screen.queryByText(text)).toBe(shown.includes(text))
        }
    })
})
