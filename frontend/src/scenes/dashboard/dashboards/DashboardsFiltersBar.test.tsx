import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { DashboardsFiltersBar } from './DashboardsFiltersBar'
import { DashboardsTab } from './dashboardsLogic'

jest.mock('kea', () => ({ ...jest.requireActual('kea'), useValues: jest.fn(), useActions: jest.fn() }))
// The member picker mounts its own logic that this test doesn't provide; it's not under test here.
jest.mock('lib/components/MemberSelectMultiplePopover', () => ({ MemberSelectMultiplePopover: () => null }))

describe('DashboardsFiltersBar', () => {
    const setFilters = jest.fn()

    afterEach(cleanup)

    beforeEach(() => {
        jest.clearAllMocks()
        ;(useActions as jest.Mock).mockReturnValue({
            setFilters,
            setTagSearch: jest.fn(),
            setShowTagPopover: jest.fn(),
            setSearch: jest.fn(),
        })
    })

    const renderBar = (folderOptions: { label: string; value: string }[]): void => {
        ;(useValues as jest.Mock).mockReturnValue({
            filters: { search: '', createdBy: 'All users', pinned: false, shared: false, tags: [], folder: null },
            currentTab: DashboardsTab.All,
            filteredTags: [],
            tagSearch: '',
            showTagPopover: false,
            folderOptions,
        })
        render(<DashboardsFiltersBar />)
    }

    it('offers the folder filter before any folder is selected', () => {
        renderBar([{ label: 'Marketing/Website', value: 'Marketing/Website' }])
        expect(screen.getByText('Folder')).toBeInTheDocument()
    })

    it('hides the folder filter when no folder holds a dashboard', () => {
        renderBar([])
        expect(screen.queryByText('Folder')).not.toBeInTheDocument()
    })

    it('applies the chosen folder', () => {
        renderBar([{ label: 'Marketing/Website', value: 'Marketing/Website' }])
        fireEvent.click(screen.getByText('Folder'))
        fireEvent.click(screen.getByText('Marketing/Website'))
        expect(setFilters).toHaveBeenCalledWith({ folder: 'Marketing/Website' })
    })
})
