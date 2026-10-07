import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { getAppContext } from 'lib/utils/getAppContext'
import { userLogic } from 'scenes/userLogic'

import { DashboardTemplateScope, DashboardTemplateType } from '~/types'

import { DashboardTemplatesTable } from './DashboardTemplatesTable'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
}))

// Render every column's cell for each row so the row-action menu (last column) is exercised, and the empty state
// when there are no rows.
jest.mock('lib/lemon-ui/LemonTable', () => ({
    LemonTable: ({ dataSource, columns, emptyState }: any) => (
        <div data-attr="mock-lemon-table">
            {dataSource.length === 0
                ? emptyState
                : dataSource.map((row: any, rowIndex: number) => (
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
// `useValues` keys only on `userLogic` below; every other logic falls through to the table values.
// Which templates a viewer can manage is decided by the logic's selectors and tested in dashboardTemplatesLogic.test.ts.
jest.mock('scenes/dashboard/dashboards/templates/dashboardTemplatesLogic', () => ({
    dashboardTemplatesLogic: jest.fn(() => ({ __mock: 'templatesTableLogic' })),
}))

jest.mock('lib/utils/getAppContext', () => ({
    getAppContext: jest.fn(() => ({})),
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock

const CURRENT_TEAM_ID = 1
const OTHER_TEAM = { id: 2, name: 'Marketing site' }

function makeTemplate(
    scope: DashboardTemplateScope,
    overrides: Partial<DashboardTemplateType> = {}
): DashboardTemplateType {
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
        ...overrides,
    }
}

function mountTable({
    isStaff,
    templates,
    searchText = null,
    loadFailed = false,
    canManage = true,
    canEditTemplates = true,
    managedInAnotherProject = false,
}: {
    isStaff: boolean
    templates: DashboardTemplateType[]
    searchText?: string | null
    loadFailed?: boolean
    canManage?: boolean
    canEditTemplates?: boolean
    managedInAnotherProject?: boolean
}): Record<string, jest.Mock> {
    // One shared action bag for every useActions() caller; the component reads disjoint keys from each.
    const actions: Record<string, jest.Mock> = {
        setTemplateFilter: jest.fn(),
        setTemplateNameOrdering: jest.fn(),
        setTemplatesTabVisibility: jest.fn(),
        clearFilters: jest.fn(),
        getAllTemplates: jest.fn(),
        deleteDashboardTemplate: jest.fn(),
        updateDashboardTemplate: jest.fn(),
        toggleTemplateOrganizationScope: jest.fn(),
        openEdit: jest.fn(),
    }
    mockedUseValues.mockImplementation((logic: unknown) => {
        if (logic === userLogic) {
            return {
                user: {
                    is_staff: isStaff,
                    team: { id: CURRENT_TEAM_ID },
                    organization: { teams: [{ id: CURRENT_TEAM_ID, name: 'Default project' }, OTHER_TEAM] },
                },
            }
        }
        return {
            allTemplates: templates,
            allTemplatesLoading: false,
            allTemplatesLoadFailed: loadFailed,
            templateFilter: searchText ?? '',
            searchText,
            hasActiveFilters: searchText !== null,
            templateNameOrdering: '',
            templatesTabVisibility: 'all',
            isStaffViewer: isStaff,
            currentTeamId: CURRENT_TEAM_ID,
            canEditTemplates,
            canManageTemplate: () => canManage,
            isManagedInAnotherProject: () => managedInAnotherProject,
        }
    })
    mockedUseActions.mockReturnValue(actions)
    render(<DashboardTemplatesTable />)
    return actions
}

const VIEWERS = [
    { label: 'staff', isStaff: true },
    { label: 'customer editor', isStaff: false },
]

describe('DashboardTemplatesTable', () => {
    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
        ;(getAppContext as jest.Mock).mockReturnValue({})
    })

    // The organization-scope toggle originally shipped in the customer menu only, so staff couldn't share a
    // template org-wide. It must be present in both the staff and the customer row menus.
    it.each(VIEWERS)('offers "Make visible to whole organization" on a team template for $label', ({ isStaff }) => {
        mountTable({ isStaff, templates: [makeTemplate('team')] })

        expect(screen.getByText('Make visible to whole organization')).toBeInTheDocument()
    })

    it.each(VIEWERS)('offers the demote action on an organization template for $label', ({ isStaff }) => {
        mountTable({ isStaff, templates: [makeTemplate('organization')] })

        expect(screen.getByText('Make visible to this project only')).toBeInTheDocument()
    })

    // Global templates are not org-shareable, so the staff guard `scope === 'team' || scope === 'organization'`
    // must keep the org toggle out. The global toggle ("...this project only") still renders, proving the menu mounted.
    it('hides the organization toggle on a global template for staff', () => {
        mountTable({ isStaff: true, templates: [makeTemplate('global')] })

        expect(screen.getByText('Make visible to this project only')).toBeInTheDocument()
        expect(screen.queryByText('Make visible to whole organization')).not.toBeInTheDocument()
    })

    it('dispatches toggleTemplateOrganizationScope with the record when the toggle is clicked', () => {
        const actions = mountTable({ isStaff: true, templates: [makeTemplate('team')] })

        fireEvent.click(screen.getByText('Make visible to whole organization'))

        expect(actions.toggleTemplateOrganizationScope).toHaveBeenCalledTimes(1)
        expect(actions.toggleTemplateOrganizationScope).toHaveBeenCalledWith(
            expect.objectContaining({ id: 'template-123', scope: 'team' })
        )
    })

    it.each(VIEWERS)('opens the edit modal when $label clicks a template name', ({ isStaff }) => {
        const template = makeTemplate('team')
        const actions = mountTable({ isStaff, templates: [template] })

        fireEvent.click(screen.getByText('My template'))

        expect(actions.openEdit).toHaveBeenCalledWith(template)
    })

    it.each([
        {
            label: 'an organization template managed in another project',
            template: makeTemplate('organization', { team_id: OTHER_TEAM.id }),
            managedInAnotherProject: true,
            canEditTemplates: true,
            lockLabel: 'Managed in Marketing site',
        },
        {
            label: 'a viewer without editor access',
            template: makeTemplate('team'),
            managedInAnotherProject: false,
            canEditTemplates: false,
            lockLabel: 'You need editor access to dashboards to manage templates',
        },
    ])(
        'shows a read-only row with a lock that explains why for $label',
        ({ template, managedInAnotherProject, canEditTemplates, lockLabel }) => {
            mountTable({
                isStaff: false,
                templates: [template],
                canManage: false,
                canEditTemplates,
                managedInAnotherProject,
            })

            expect(screen.getByLabelText(lockLabel)).toBeInTheDocument()
            expect(document.querySelector('[data-attr="dashboard-template-name-edit"]')).not.toBeInTheDocument()
            expect(screen.queryByText('Edit')).not.toBeInTheDocument()
        }
    )

    it.each([
        { label: 'staff', isStaff: true, showsOfficial: true },
        { label: 'customers', isStaff: false, showsOfficial: false },
    ])('$label sees official templates mentioned and filterable: $showsOfficial', ({ isStaff, showsOfficial }) => {
        mountTable({ isStaff, templates: [makeTemplate('team')] })
        const expectedCount = showsOfficial ? 1 : 0

        expect(screen.queryAllByText(/PostHog's official templates/)).toHaveLength(expectedCount)
        expect(document.querySelectorAll('[data-attr="dashboard-templates-filter-official"]')).toHaveLength(
            expectedCount
        )
    })

    describe('empty states', () => {
        it('explains how to add a template when there are none', () => {
            mountTable({ isStaff: false, templates: [] })

            expect(screen.getByText('No templates yet')).toBeInTheDocument()
            expect(screen.getByText('Browse PostHog templates')).toBeInTheDocument()
        })

        it.each([
            {
                label: 'a search matches nothing',
                searchText: 'churn',
                loadFailed: false,
                title: 'No templates match "churn"',
                button: 'Clear filters',
                action: 'clearFilters',
            },
            {
                label: 'the templates failed to load',
                searchText: null,
                loadFailed: true,
                title: "Couldn't load templates",
                button: 'Try again',
                action: 'getAllTemplates',
            },
        ])('offers a next step when $label', ({ searchText, loadFailed, title, button, action }) => {
            const actions = mountTable({ isStaff: false, templates: [], searchText, loadFailed })

            expect(screen.getByText(title)).toBeInTheDocument()
            fireEvent.click(screen.getByText(button))

            expect(actions[action]).toHaveBeenCalledTimes(1)
        })
    })
})
