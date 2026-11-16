import { render } from '@testing-library/react'

import { LiveEventsFeed, getWebAnalyticsLiveFeedColumns } from './LiveEventsFeed'

describe('LiveEventsFeed', () => {
    it('puts the recordings action after the time column and gives it room', () => {
        const { container } = render(<LiveEventsFeed events={[]} columns={getWebAnalyticsLiveFeedColumns(true)} />)

        expect(
            Array.from(container.querySelectorAll('thead tr:not(.LemonTable__row--grouping) th'))
                .map((header) => header.textContent)
                .filter(Boolean)
        ).toEqual(['Event', 'Person distinct ID', 'URL / Screen', 'Time'])
        expect(container.querySelector('colgroup col:last-child')?.getAttribute('style')).toContain('56px')
    })
})
