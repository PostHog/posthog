import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { initKeaTests } from '~/test/init'

import { AdvertisementCard, DISMISS_SETTLE_MS } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'

describe('AdvertisementCard', () => {
    const onClose = jest.fn()

    function renderCard(): ReturnType<typeof navPanelAdvertisementLogic.build> {
        render(
            <BindLogic logic={navPanelAdvertisementLogic} props={{ dismissKey: 'test-card' }}>
                <AdvertisementCard
                    title="Session replay"
                    text="Watch what people actually do."
                    to="/project/1/replay"
                    onClose={onClose}
                />
            </BindLogic>
        )
        return navPanelAdvertisementLogic({ dismissKey: 'test-card' })
    }

    beforeEach(() => {
        initKeaTests()
        onClose.mockClear()
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
        cleanup()
    })

    // The card used to be wrapped whole in its link, so the dismiss icon was a nested control and
    // every click near the card's corner dismissed instead of navigating.
    it('keeps the dismiss control outside the card link', () => {
        renderCard()

        expect(screen.getByLabelText('Dismiss').closest('a')).toBeNull()
        expect(document.querySelector('a[href="/project/1/replay"]')).toBeInTheDocument()
    })

    it.each([
        ['while the card is still settling', DISMISS_SETTLE_MS - 1, false],
        ['once the card has settled', DISMISS_SETTLE_MS, true],
    ])('dismisses %s: %s', (_description, elapsedMs, expectedHidden) => {
        const logic = renderCard()

        jest.advanceTimersByTime(elapsedMs)
        fireEvent.click(screen.getByLabelText('Dismiss'))

        expect(logic.values.hidden).toBe(expectedHidden)
        expect(onClose).toHaveBeenCalledTimes(expectedHidden ? 1 : 0)
    })
})
