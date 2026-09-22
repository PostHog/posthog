import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { DashboardsFiltersBar } from './DashboardsFiltersBar'
import { DashboardsTab } from './dashboardsLogic'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn(), useActions: jest.fn() }))
jest.mock('lib/components/MemberSelectMultiplePopover', () => ({ MemberSelectMultiplePopover: () => null }))
jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    Popover: ({ children, overlay }: { children: ReactNode; overlay: ReactNode }) => (
        <>
            {children}
            {overlay}
        </>
    ),
}))

describe('DashboardsFiltersBar', () => {
    it('loads more tags when the tag list reaches its bottom', () => {
        const loadMoreTagResults = jest.fn()
        ;(useActions as jest.Mock).mockReturnValue({
            loadMoreTagResults,
            setFilters: jest.fn(),
            setTagSearch: jest.fn(),
            setShowTagPopover: jest.fn(),
            setSearch: jest.fn(),
        })
        ;(useValues as jest.Mock).mockReturnValue({
            filters: { createdBy: 'All users', search: '', tags: [] },
            currentTab: DashboardsTab.All,
            tagPageLoading: false,
            tagResults: ['alpha'],
            tagSearch: '',
            showTagPopover: true,
        })

        const { rerender } = render(<DashboardsFiltersBar />)

        const tagList = document.querySelector<HTMLDivElement>('[data-attr="dashboard-tags-list"]')
        if (!tagList) {
            throw new Error('Tag list is not rendered')
        }
        Object.defineProperties(tagList, {
            clientHeight: { value: 100 },
            scrollHeight: { value: 200 },
            scrollTop: { value: 101 },
        })

        fireEvent.scroll(tagList)

        expect(loadMoreTagResults).toHaveBeenCalledTimes(1)
        expect(screen.queryByText('Load more tags')).not.toBeInTheDocument()

        ;(useValues as jest.Mock).mockReturnValue({
            filters: { createdBy: 'All users', search: '', tags: [] },
            currentTab: DashboardsTab.All,
            tagPageLoading: true,
            tagResults: [],
            tagSearch: '',
            showTagPopover: true,
        })
        rerender(<DashboardsFiltersBar />)

        expect(screen.getAllByText('Loading…')).toHaveLength(5)
    })

    it('clears all selected tags from the tag picker', () => {
        const setFilters = jest.fn()
        ;(useActions as jest.Mock).mockReturnValue({
            loadMoreTagResults: jest.fn(),
            setFilters,
            setTagSearch: jest.fn(),
            setShowTagPopover: jest.fn(),
            setSearch: jest.fn(),
        })
        ;(useValues as jest.Mock).mockReturnValue({
            filters: { createdBy: 'All users', search: '', tags: ['growth', 'analytics'] },
            currentTab: DashboardsTab.All,
            tagPageLoading: false,
            tagResults: ['growth', 'analytics'],
            tagSearch: '',
            showTagPopover: true,
        })

        render(<DashboardsFiltersBar />)
        fireEvent.click(document.querySelector('[data-attr="dashboard-tags-clear-selection"]')!)

        expect(setFilters).toHaveBeenCalledWith({ tags: [] })
    })
})
