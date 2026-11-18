import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ResourceTagFilter } from './ResourceTagFilter'

describe('ResourceTagFilter', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({ get: { '/api/projects/:teamId/tags': { results: ['quality', 'production'], next: null } } })
    })
    afterEach(() => cleanup())

    it.each(['tags', 'tag_match'])('omits the current page when changing %s', async (field) => {
        const onChange = jest.fn()
        const filters = { tags: ['quality', 'production'], tag_match: 'any' as const, page: 3 }
        render(
            <Provider>
                <ResourceTagFilter filters={filters} onChange={onChange} />
            </Provider>
        )

        if (field === 'tags') {
            await userEvent.click(screen.getByText('2 tags'))
            await userEvent.click(await screen.findByLabelText('quality'))
            expect(onChange).toHaveBeenCalledWith({ tags: ['production'], tag_match: 'any' })
        } else {
            await userEvent.click(screen.getByText('Match any'))
            await userEvent.click(screen.getByText('Match all'))
            expect(onChange).toHaveBeenCalledWith({ tags: ['quality', 'production'], tag_match: 'all' })
        }
    })
})
