import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

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
    })

    it('does not run the onClick of a wrapping element when the overlay is clicked', () => {
        const onWrapperClick = jest.fn()
        const { overlayText } = renderSessionDuration(onWrapperClick)

        fireEvent.click(overlayText)

        expect(onWrapperClick).not.toHaveBeenCalled()
    })
})
