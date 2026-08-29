import { fireEvent, render, screen } from '@testing-library/react'
import posthog from 'posthog-js'

import { SDK, SDKTag } from '~/types'

import { SDKGrid } from './SDKGrid'
import { SDKGridProps } from './types'

const iosSDK: SDK = {
    name: 'iOS',
    key: 'ios',
    tags: [SDKTag.MOBILE],
    image: 'ios.png',
    docsLink: 'https://posthog.com/docs/libraries/ios',
}

const reachOutButton = (): Element | null => document.querySelector('[data-attr="onboarding-reach-out-to-us-button"]')

function renderGrid(overrides: Partial<SDKGridProps>): SDKGridProps {
    const props: SDKGridProps = {
        filteredSDKs: [iosSDK],
        searchTerm: '',
        selectedTag: null,
        tags: ['All'],
        onSDKClick: jest.fn(),
        onSearchChange: jest.fn(),
        onTagChange: jest.fn(),
        currentTeam: null,
        showTopControls: false,
        installationComplete: false,
        showTopSkipButton: false,
        ...overrides,
    }
    render(<SDKGrid {...props} />)
    return props
}

describe('SDKGrid', () => {
    beforeEach(() => {
        jest.mocked(posthog.displaySurvey).mockClear()
    })

    it('hides the no-results card when a search still has a match', () => {
        renderGrid({ searchTerm: 'ios', filteredSDKs: [iosSDK] })

        expect(screen.getByText('iOS')).not.toBeNull()
        expect(screen.queryByText('No SDKs match your search')).toBeNull()
        expect(reachOutButton()).toBeNull()
    })

    it('shows the empty state and clears both filters when nothing matches', () => {
        const props = renderGrid({ searchTerm: 'zzz', selectedTag: SDKTag.MOBILE, filteredSDKs: [] })

        expect(screen.getByText('No SDKs match your search')).not.toBeNull()
        fireEvent.click(screen.getByRole('button', { name: 'Show all SDKs' }))
        expect(props.onSearchChange).toHaveBeenCalledWith('')
        expect(props.onTagChange).toHaveBeenCalledWith(null)
    })

    it('opens the missing-SDK survey when the reach-out button is clicked', () => {
        renderGrid({ searchTerm: 'zzz', filteredSDKs: [] })

        fireEvent.click(reachOutButton() as Element)
        expect(posthog.displaySurvey).toHaveBeenCalledWith('019b47ab-5f19-0000-7f31-4f9681cde589', expect.any(Object))
    })
})
