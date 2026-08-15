import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { Capability } from '../maxCapabilities'
import { CapabilityBadges } from './CapabilityBadges'

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: jest.fn(),
}))

const ANALYZE: Capability = {
    key: 'analyze',
    label: 'Analyze',
    iconType: 'default_icon_type',
    suggestions: [],
}

describe('CapabilityBadges', () => {
    beforeEach(() => {
        ;(useFeatureFlag as jest.Mock).mockReturnValue(false)
    })

    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    // Guards the homepage dead-click: with a typed question in the composer, a badge click must
    // submit that text rather than only swapping the suggestion cards (which are hidden while the
    // user is typing, so a filter-only click has no visible effect).
    it('submits the typed text instead of filtering when the composer has text', () => {
        const onSelect = jest.fn()
        const onSubmitTyped = jest.fn()

        render(
            <CapabilityBadges
                capabilities={[ANALYZE]}
                selectedKey={null}
                onSelect={onSelect}
                hasTypedText
                onSubmitTyped={onSubmitTyped}
            />
        )

        fireEvent.click(screen.getByTestId('capability-badge-analyze'))

        expect(onSubmitTyped).toHaveBeenCalledTimes(1)
        expect(onSelect).not.toHaveBeenCalled()
    })

    it('toggles the filter when the composer is empty', () => {
        const onSelect = jest.fn()
        const onSubmitTyped = jest.fn()

        render(
            <CapabilityBadges
                capabilities={[ANALYZE]}
                selectedKey={null}
                onSelect={onSelect}
                hasTypedText={false}
                onSubmitTyped={onSubmitTyped}
            />
        )

        fireEvent.click(screen.getByTestId('capability-badge-analyze'))

        expect(onSelect).toHaveBeenCalledWith('analyze')
        expect(onSubmitTyped).not.toHaveBeenCalled()
    })
})
