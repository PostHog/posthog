import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { EmailPreviewThumbnail } from './EmailPreviewThumbnail'

describe('EmailPreviewThumbnail', () => {
    // The design rides in the iframe's `srcdoc`, which the recorder serializes like any attribute.
    it('keeps the email design out of session replay', () => {
        const { container } = render(
            <EmailPreviewThumbnail html="<p>Spring sale</p>" title="Spring sale preview" size="card" />
        )

        expect(container.querySelector('iframe')).toHaveClass('ph-no-capture')
    })

    // Each card frames a whole email, so without this its links are tab stops the caller never wanted.
    it('stays out of the tab order', () => {
        const { container } = render(
            <EmailPreviewThumbnail html="<p><a href='/x'>Shop now</a></p>" title="Spring sale preview" size="card" />
        )

        expect(container.querySelector('iframe')).toHaveAttribute('tabindex', '-1')
    })
})
