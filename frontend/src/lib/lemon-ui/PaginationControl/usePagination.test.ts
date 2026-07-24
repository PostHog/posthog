import { act, renderHook } from '@testing-library/react'
import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { usePagination } from './usePagination'

const DATA = ['a', 'b', 'c']

describe('usePagination', () => {
    beforeEach(() => {
        initKeaTests()
        router.actions.push('/table')
    })

    it('setCurrentPage pushes the page into the URL by default', () => {
        const { result } = renderHook(() =>
            usePagination(DATA, { controlled: true, pageSize: 1, currentPage: 1, entryCount: 3 })
        )
        act(() => result.current.setCurrentPage(2))
        expect(router.values.searchParams.page).toBe(2)
    })

    it('setCurrentPage leaves the URL alone when useUrl is false', () => {
        const { result } = renderHook(() =>
            usePagination(DATA, { controlled: true, pageSize: 1, currentPage: 1, entryCount: 3, useUrl: false })
        )
        act(() => result.current.setCurrentPage(2))
        expect(router.values.searchParams.page).toBeUndefined()
    })
})
