import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { userHasAccess } from 'lib/utils/accessControlUtils'
import { getAppContext } from 'lib/utils/getAppContext'
import { userLogic } from 'scenes/userLogic'

import { DashboardTemplateScope, DashboardTemplateType } from '~/types'

import { DashboardTemplatesTable } from './DashboardTemplatesTable'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))

// Render every column's cell for each row so the row-action menu (last column) is exercised.
jest.mock('lib/lemon-ui/LemonTable', () => ({
    LemonTable: ({ dataSource, columns }: any) => (
        <div data-attr="mock-lemon-table">
            {dataSource.map((row: any, rowIndex: number) => (
                <div key={rowIndex}>
                    {columns.map((col: any, colIndex: number) => (
                        <div key={colIndex}>
                            {col.render
                                ? col.render(col.dataIndex ? row[col.dataIndex] : undefined, row, rowIndex)
                                : null}
                        </div>
                    ))}
                </div>
            ))}
        </div>
    ),
}))

// `More` renders its overlay lazily in a popover; expose it inline so the menu items are queryable.
jest.mock('lib/lemon-ui/LemonButton/More', () => ({
    More: ({ overlay }: any) => <div data-attr="mock-more">{overlay}</div>,
}))

// The table calls `dashboardTemplatesLogic({...})` at module load; return a stable sentinel so that import works.
// `useValues` keys only on `userLogic` below — every other logic falls through to the table-values branch.
jest.mock('scenes/dashboard/dashboards/templates/dashboardTemplatesLogic', () => ({
    dashboardTemplatesLogic: jest.fn(() => ({ __mock: 'templatesTableLogic' })),
}))

jest.mock('lib/utils/getAppContext', () => ({
    getAppContext: jest.fn(() => ({})),
}))

jest.mock('lib/utils/accessControlUtils', () => ({
    userHasAccess: jest.fn(() => true),
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock

const CURRENT_TEAM_ID = 1

function makeTemplate(scope: DashboardTemplateScope): DashboardTemplateType {
    // Only id/template_name/tiles are required on DashboardTemplateType; the rest are optional, so no cast is needed.
    return {
        id: 'template-123',
        template_name: 'My template',
        dashboard_description: 'desc',
        tags: [],
        tiles: [],
        scope,
        team_id: CURRENT_TEAM_ID,
        created_at: '2024-01-01T00:00:00Z',
        created_by: null,
    }
}

function mountTable({
    isStaff,
    scope,
}: {
    isStaff: boolean
    scope: DashboardTemplateScope
}): Record<string, jest.Mock> {
    // One shared action bag for all three useActions() callers; the component reads disjoint keys from each.
    const actions: Record<string, jest.Mock> = {
        setTemplateFilter: jest.fn(),
        setTemplateNameOrdering: jest.fn(),
        setTemplatesTabVisibility: jest.fn(),
        deleteDashboardTemplate: jest.fn(),
        updateDashboardTemplate: jest.fn(),
        toggleTemplateOrganizationScope: jest.fn(),
        openEdit: jest.fn(),
    }
    mockedUseValues.mockImplementation((logic: unknown) => {
        if (logic === userLogic) {
            return { user: { is_staff: isStaff, team: { id: CURRENT_TEAM_ID } } }
        }
        return {
            allTemplates: [makeTemplate(scope)],
            allTemplatesLoading: false,
            templateFilter: '',
            templateNameOrdering: '',
            templatesTabVisibility: 'all',
        }
    })
    mockedUseActions.mockReturnValue(actions)
    render(<DashboardTemplatesTable />)
    return actions
}

describe('DashboardTemplatesTable', () => {
    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
        ;(getAppContext as jest.Mock).mockReturnValue({})
        ;(userHasAccess as jest.Mock).mockReturnValue(true)
    })

    // The organization-scope toggle originally shipped in the customer menu only, so staff couldn't share a
    // template org-wide. It must be present in both the staff and the customer row menus.
    it.each([
        { label: 'staff', isStaff: true },
        { label: 'customer editor', isStaff: false },
    ])('offers "Make visible to whole organization" on a team template for $label', ({ isStaff }) => {
        mountTable({ isStaff, scope: 'team' })

        expect(screen.getByText('Make visible to whole organization')).toBeInTheDocument()
    })

    it.each([
        { label: 'staff', isStaff: true },
        { label: 'customer editor', isStaff: false },
    ])('offers the demote action on an organization template for $label', ({ isStaff }) => {
        mountTable({ isStaff, scope: 'organization' })

        expect(screen.getByText('Make visible to this team only')).toBeInTheDocument()
    })

    // Global templates are not org-shareable, so the staff guard `scope === 'team' || scope === 'organization'`
    // must keep the org toggle out. The global toggle ("...this team only") still renders, proving the menu mounted.
    it('hides the organization toggle on a global template for staff', () => {
        mountTable({ isStaff: true, scope: 'global' })

        expect(screen.getByText('Make visible to this team only')).toBeInTheDocument()
        expect(screen.queryByText('Make visible to whole organization')).not.toBeInTheDocument()
    })

    it('dispatches toggleTemplateOrganizationScope with the record when the toggle is clicked', () => {
        const actions = mountTable({ isStaff: true, scope: 'team' })

        fireEvent.click(screen.getByText('Make visible to whole organization'))

        expect(actions.toggleTemplateOrganizationScope).toHaveBeenCalledTimes(1)
        expect(actions.toggleTemplateOrganizationScope).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'template-123', scope: 'team' })
        )
    })
})
