import { act, RenderHookResult, renderHook } from '@testing-library/react'

import { NodeKind } from '~/queries/schema/schema-general'

import { useDebouncedQuery } from './useDebouncedQuery'

type SearchQuery = { kind: NodeKind.ActorsQuery; search?: string }
type DebouncedResult = { value: string; onChange: (value: string) => void }

function makeQuery(search: string): SearchQuery {
    return { kind: NodeKind.ActorsQuery, search }
}

function renderDebounced(
    query: SearchQuery,
    setQuery: (query: SearchQuery) => void
): RenderHookResult<DebouncedResult, { query: SearchQuery }> {
    return renderHook(
        ({ query }) =>
            useDebouncedQuery<SearchQuery, string>(
                query,
                setQuery,
                (q) => q.search || '',
                (q, value) => ({ ...q, search: value })
            ),
        {
            initialProps: { query },
        }
    )
}

describe('useDebouncedQuery', () => {
    beforeEach(() => jest.useFakeTimers())
    afterEach(() => jest.useRealTimers())

    it('resyncs the input value when the query changes from outside', () => {
        const setQuery = jest.fn()
        const { result, rerender } = renderDebounced(makeQuery('alice'), setQuery)
        expect(result.current.value).toBe('alice')

        rerender({ query: makeQuery('') })

        expect(result.current.value).toBe('')
    })

    it('debounces onChange before calling setQuery', () => {
        const setQuery = jest.fn()
        const { result } = renderDebounced(makeQuery(''), setQuery)

        act(() => result.current.onChange('bob'))
        expect(result.current.value).toBe('bob')
        expect(setQuery).not.toHaveBeenCalled()

        act(() => jest.advanceTimersByTime(300))
        expect(setQuery).toHaveBeenCalledWith({ kind: NodeKind.ActorsQuery, search: 'bob' })
    })

    it('does not call setQuery for a pending change after unmount', () => {
        const setQuery = jest.fn()
        const { result, unmount } = renderDebounced(makeQuery(''), setQuery)

        act(() => result.current.onChange('bob'))
        unmount()
        act(() => jest.advanceTimersByTime(300))

        expect(setQuery).not.toHaveBeenCalled()
    })
})
