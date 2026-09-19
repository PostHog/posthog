import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { lemonBannerLogic } from 'lib/lemon-ui/LemonBanner/lemonBannerLogic'

import { initKeaTests } from '~/test/init'

import { ShelfVisionOffer } from './ExperimentBehaviorComparison'
import { SCANNER_CROSS_SELL_DISMISS_KEY } from './experimentReplayTabLogic'

describe('ShelfVisionOffer', () => {
    const crossSell = { url: '/replay/vision/scanner/new?experiment=42', onClick: jest.fn() }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('reads as a sentence with a link rather than a pitch with a button', () => {
        // A boxed banner with an action button sat here, directly under the box that says the shelf
        // found nothing. Two boxes in a row read as an ad rather than as the answer to the question
        // an empty shelf leaves the reader holding.
        render(
            <Provider>
                <ShelfVisionOffer crossSell={crossSell} />
            </Provider>
        )

        // Project-prefixed by Link, so the assertion is on the destination the shelf chose.
        expect(screen.getByText('Replay vision').closest('a')).toHaveAttribute(
            'href',
            expect.stringContaining(crossSell.url)
        )
        expect(screen.queryByRole('button')).not.toBeInTheDocument()
        expect(document.querySelector('.LemonBanner')).toBeNull()
    })

    it('stays away once the reader has turned the same offer off', () => {
        // The tab's banner carries the only close button this offer has, and a shelf showing this
        // line is a shelf that took that banner away. Without the check, a reader who said no would
        // have nothing left to say it with.
        const banner = lemonBannerLogic({ dismissKey: SCANNER_CROSS_SELL_DISMISS_KEY })
        banner.mount()
        banner.actions.dismiss()

        render(
            <Provider>
                <ShelfVisionOffer crossSell={crossSell} />
            </Provider>
        )

        expect(screen.queryByText('Replay vision')).not.toBeInTheDocument()
    })
})
