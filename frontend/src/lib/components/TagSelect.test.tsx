import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
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

        await userEvent.click(screen.getByText('revenue'))
        await waitFor(() => expect(screen.getByLabelText('topic-1 (75)')).toBeInTheDocument())
        expect(screen.getByText('Clear selection')).toBeInTheDocument()
        expect(screen.queryByLabelText('topic-75 (1)')).not.toBeInTheDocument()
        await userEvent.type(screen.getByPlaceholderText('Search tags'), 'topic-75')
        await waitFor(() => expect(screen.getByLabelText('topic-75 (1)')).toBeInTheDocument())
        expect(screen.queryByLabelText('revenue (1)')).not.toBeInTheDocument()
        expect(screen.queryByText('Clear selection')).not.toBeInTheDocument()
        await userEvent.click(screen.getByLabelText('topic-75 (1)'))
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

        await userEvent.click(screen.getByText('Any tags'))
        await userEvent.click(
            await screen.findByText("Couldn't load tags. Try again.", { selector: '.LemonButton__content' })
        )
        await waitFor(() => expect(screen.getByLabelText('available')).toBeInTheDocument())
        expect(screen.queryByText('Clear selection')).not.toBeInTheDocument()
        expect(loadTags).toHaveBeenCalledTimes(2)
    })

    it('ignores a page that finishes after the picker closes', async () => {
        let resolveFirstPage: (page: { results: { tag: string }[]; hasMore: boolean }) => void = () => {}
        let resolveNextPage: (page: { results: { tag: string }[]; hasMore: boolean }) => void = () => {}
        const loadTags = jest
            .fn()
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveFirstPage = resolve
                    })
            )
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveNextPage = resolve
                    })
            )
        render(
            <Provider>
                <TagSelect value={['selected']} onChange={jest.fn()} loadTags={loadTags} />
            </Provider>
        )

        await userEvent.click(screen.getAllByText('selected')[0].closest('button')!)
        await waitFor(() => expect(loadTags).toHaveBeenCalledTimes(1))
        await userEvent.click(screen.getByText('Clear selection'))
        expect(screen.getAllByText('selected')[0].closest('button')!).toHaveFocus()
        await act(async () => {
            resolveFirstPage({ results: [{ tag: 'stale' }], hasMore: false })
        })
        await userEvent.click(screen.getAllByText('selected')[0].closest('button')!)
        await waitFor(() => expect(loadTags).toHaveBeenCalledTimes(2))
        expect(screen.queryByLabelText('stale')).not.toBeInTheDocument()
        await act(async () => {
            resolveNextPage({ results: [{ tag: 'current' }], hasMore: false })
        })
        expect(screen.getByLabelText('current')).toBeInTheDocument()
    })
})
