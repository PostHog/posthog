import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { NotFound } from './index'

describe('NotFound', () => {
    beforeEach(() => {
        initKeaTests()
    })

    // The escape hatch is keyed off the object name, which every caller spells lowercase.
    it('offers an event search for a missing person', () => {
        // Unmounting matters: the tooltip schedules an async update that errors after teardown.
        const { unmount } = render(
            <Provider>
                <NotFound object="person" meta={{ urlId: '019f9c1f-0000-7000-8000-000000000000' }} />
            </Provider>
        )

        const link = screen.getByText('View events').closest('a')
        expect(link).toHaveAttribute('href', expect.stringContaining('019f9c1f-0000-7000-8000-000000000000'))

        unmount()
    })
})
