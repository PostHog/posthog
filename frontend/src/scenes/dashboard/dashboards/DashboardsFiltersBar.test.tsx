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

    const renderBar = (
        folderOptions: { label: string; value: string }[],
        folder: string | null = null
    ): ReturnType<typeof render> => {
        ;(useValues as jest.Mock).mockReturnValue({
            filters: { search: '', createdBy: 'All users', pinned: false, shared: false, tags: [], folder },
            currentTab: DashboardsTab.All,
            filteredTags: [],
            tagSearch: '',
            showTagPopover: false,
            folderOptions,
        })
        return render(<DashboardsFiltersBar />)
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

    // The project-root folder is the empty string, which is falsy: without the sentinel mapping the
    // select can neither apply nor clear it, so these two guard that path.
    it('applies the project-root folder as an empty-string filter', () => {
        renderBar([{ label: 'Project root', value: '' }])
        fireEvent.click(screen.getByText('Folder'))
        fireEvent.click(screen.getByText('Project root'))
        expect(setFilters).toHaveBeenCalledWith({ folder: '' })
    })

    it('clears an active project-root folder filter', () => {
        const { container } = renderBar([{ label: 'Project root', value: '' }], '')
        expect(screen.getByText('Project root')).toBeInTheDocument()
        const clearButton = container.querySelector('.LemonButtonWithSideAction__side-button button')
        expect(clearButton).not.toBeNull()
        fireEvent.click(clearButton as Element)
        expect(setFilters).toHaveBeenCalledWith({ folder: null })
    })

    // An active filter can outlive its folder in the options list: the folder's dashboards get moved
    // or deleted, or the filter is restored from the URL before any folder holds a dashboard. The
    // select must stay visible with the current folder labelled, so the filter remains clearable.
    it.each([
        ['a named folder that no longer holds dashboards', 'Marketing/Website', 'Marketing/Website'],
        ['the project root after its dashboards were moved out', '', 'Project root'],
    ])('keeps an active folder filter clearable when no folder holds a dashboard (%s)', (_desc, folder, label) => {
        const { container } = renderBar([], folder)
        expect(screen.getByText(label)).toBeInTheDocument()
        const clearButton = container.querySelector('.LemonButtonWithSideAction__side-button button')
        expect(clearButton).not.toBeNull()
        fireEvent.click(clearButton as Element)
        expect(setFilters).toHaveBeenCalledWith({ folder: null })
    })
})
