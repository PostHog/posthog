import { render, screen } from '@testing-library/react'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'

describe('CopyToClipboardInline', () => {
    it('keeps the caller data-attr on the icon-only button', () => {
        render(<CopyToClipboardInline explicitValue="https://example.com" data-attr="player-meta-copy-url" />)

        expect(screen.getByRole('button').getAttribute('data-attr')).toBe('player-meta-copy-url')
    })

    it('keeps the caller data-attr when there are children', () => {
        render(
            <CopyToClipboardInline explicitValue="https://example.com" data-attr="player-meta-copy-url">
                https://example.com
            </CopyToClipboardInline>
        )

        expect(screen.getByText('https://example.com').parentElement?.getAttribute('data-attr')).toBe(
            'player-meta-copy-url'
        )
    })
})
