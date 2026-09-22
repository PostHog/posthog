import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { initKeaTests } from '~/test/init'

import { AdvertisementCard, DISMISS_SETTLE_MS } from './navPanelAdShared'
import { navPanelAdvertisementLogic } from './NavPanelAdvertisementLogic'

describe('AdvertisementCard', () => {
    const onClose = jest.fn()

    function renderCard(): ReturnType<typeof navPanelAdvertisementLogic.build> {
        const logic = navPanelAdvertisementLogic({ dismissKey: 'test-card' })
        logic.mount()
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
        return logic
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

        const dismiss = screen.getByRole('button', { name: 'Dismiss' })
        expect(dismiss.closest('a')).toBeNull()
        expect(screen.getByRole('link')).toBeInTheDocument()
    })

    it.each([
        ['while the card is still settling', DISMISS_SETTLE_MS - 1, false],
        ['once the card has settled', DISMISS_SETTLE_MS, true],
    ])('dismisses %s: %s', (_description, elapsedMs, expectedHidden) => {
        const logic = renderCard()

        jest.advanceTimersByTime(elapsedMs)
        fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))

        expect(logic.values.hidden).toBe(expectedHidden)
        expect(onClose).toHaveBeenCalledTimes(expectedHidden ? 1 : 0)
    })
})
