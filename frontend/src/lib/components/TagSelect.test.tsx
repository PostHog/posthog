import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { TagSelect } from './TagSelect'

describe('TagSelect', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => cleanup())

    it('searches only the supplied tags and keeps multi-selection when the search changes', async () => {
        const onChange = jest.fn()
        const options = [
            { tag: 'revenue', count: 1 },
            ...Array.from({ length: 75 }, (_, index) => ({ tag: `topic-${index + 1}`, count: 75 - index })),
        ]
        render(
            <Provider>
                <TagSelect defaultLabel="Any tag" options={options} value={['revenue']} onChange={onChange} />
            </Provider>
        )

        await userEvent.click(screen.getByRole('button', { name: 'revenue' }))
        await waitFor(() => expect(screen.getByRole('checkbox', { name: /topic-1\b/ })).toBeInTheDocument())
        expect(screen.queryByRole('checkbox', { name: /topic-75/ })).not.toBeInTheDocument()
        await userEvent.type(screen.getByPlaceholderText('Search tags'), 'topic-75')
        await waitFor(() => expect(screen.getByRole('checkbox', { name: /topic-75/ })).toBeInTheDocument())
        expect(screen.queryByRole('checkbox', { name: /revenue/ })).not.toBeInTheDocument()
        await userEvent.click(screen.getByRole('checkbox', { name: /topic-75/ }))
        expect(onChange).toHaveBeenCalledWith(['revenue', 'topic-75'])
    })

    it('shows a retry when a tag page fails to load', async () => {
        const loadTags = jest
            .fn()
            .mockRejectedValueOnce(new Error('Request failed'))
            .mockResolvedValue({ results: [{ tag: 'available' }], hasMore: false })
        render(
            <Provider>
                <TagSelect value={[]} onChange={jest.fn()} loadTags={loadTags} />
            </Provider>
        )

        await userEvent.click(screen.getByRole('button', { name: 'Any tags' }))
        await userEvent.click(await screen.findByRole('button', { name: "Couldn't load tags. Try again." }))
        await waitFor(() => expect(screen.getByRole('checkbox', { name: 'available' })).toBeInTheDocument())
        expect(loadTags).toHaveBeenCalledTimes(2)
    })
})
