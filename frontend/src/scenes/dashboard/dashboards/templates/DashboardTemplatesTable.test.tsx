import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import { userHasAccess } from 'lib/utils/accessControlUtils'
import { getAppContext } from 'lib/utils/getAppContext'
import { newDashboardLogic } from 'scenes/dashboard/newDashboardLogic'
import { userLogic } from 'scenes/userLogic'

import { DashboardTemplateScope, DashboardTemplateType, DashboardTemplateVariableType } from '~/types'

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
// `useValues` keys on `userLogic` and `newDashboardLogic` below; every other logic falls through to the table values.
jest.mock('scenes/dashboard/dashboards/templates/dashboardTemplatesLogic', () => ({
    dashboardTemplatesLogic: jest.fn(() => ({ __mock: 'templatesTableLogic' })),
}))

// A sentinel keeps the real logic and its large import graph out of the test.
jest.mock('scenes/dashboard/newDashboardLogic', () => ({
    newDashboardLogic: { __mock: 'newDashboardLogic' },
}))

jest.mock('lib/utils/getAppContext', () => ({
    getAppContext: jest.fn(() => ({})),
}))

jest.mock('lib/utils/accessControlUtils', () => ({
    userHasAccess: jest.fn(() => true),
    getAccessControlDisabledReason: jest.fn(() => null),
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock

const CURRENT_TEAM_ID = 1
const OTHER_TEAM = { id: 2, name: 'Marketing site' }

const EVENT_VARIABLE: DashboardTemplateVariableType = {
    id: 'SIGNUP_EVENT',
    name: 'Signup event',
    description: 'The event that marks a signup',
    type: 'event',
    default: {},
    required: true,
}

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
        variables: [],
        ...overrides,
    }
}

function mountTable({
    isStaff,
    templates,
    dashboardCreationLoading = false,
    searchText = null,
}: {
    isStaff: boolean
    templates: DashboardTemplateType[]
    dashboardCreationLoading?: boolean
    searchText?: string | null
}): Record<string, jest.Mock> {
    // One shared action bag for every useActions() caller; the component reads disjoint keys from each.
    const actions: Record<string, jest.Mock> = {
        setTemplateFilter: jest.fn(),
        setTemplateNameOrdering: jest.fn(),
        setTemplatesTabVisibility: jest.fn(),
        deleteDashboardTemplate: jest.fn(),
        updateDashboardTemplate: jest.fn(),
        toggleTemplateOrganizationScope: jest.fn(),
        openEdit: jest.fn(),
        setIsLoading: jest.fn(),
        createDashboardFromTemplate: jest.fn(),
        showVariableSelectModal: jest.fn(),
        setActiveDashboardTemplate: jest.fn(),
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
        if (logic === newDashboardLogic) {
            return { isLoading: dashboardCreationLoading, newDashboardModalVisible: false }
        }
        return {
            allTemplates: templates,
            allTemplatesLoading: false,
            templateFilter: searchText ?? '',
            searchText,
            templateNameOrdering: '',
            templatesTabVisibility: 'all',
            isStaffViewer: isStaff,
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
        ;(userHasAccess as jest.Mock).mockReturnValue(true)
    })

    // The organization-scope toggle originally shipped in the customer menu only, so staff couldn't share a
    // template org-wide. It must be present in both the staff and the customer row menus.
    it.each(VIEWERS)('offers "Make visible to whole organization" on a team template for $label', ({ isStaff }) => {
        mountTable({ isStaff, templates: [makeTemplate('team')] })

        expect(screen.getByText('Make visible to whole organization')).toBeInTheDocument()
    })

    it.each(VIEWERS)('offers the demote action on an organization template for $label', ({ isStaff }) => {
        mountTable({ isStaff, templates: [makeTemplate('organization')] })

        expect(screen.getByText('Make visible to this team only')).toBeInTheDocument()
    })

    // Global templates are not org-shareable, so the staff guard `scope === 'team' || scope === 'organization'`
    // must keep the org toggle out. The global toggle ("...this team only") still renders, proving the menu mounted.
    it('hides the organization toggle on a global template for staff', () => {
        mountTable({ isStaff: true, templates: [makeTemplate('global')] })

        expect(screen.getByText('Make visible to this team only')).toBeInTheDocument()
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

    describe('New dashboard from template', () => {
        it.each(VIEWERS)(
            'creates the dashboard straight away for $label when there are no variables',
            ({ isStaff }) => {
                const template = makeTemplate('team')
                const actions = mountTable({ isStaff, templates: [template] })

                fireEvent.click(screen.getByText('New dashboard from template'))

                expect(actions.createDashboardFromTemplate).toHaveBeenCalledWith(
                    template,
                    [],
                    true,
                    'dashboard_templates_manage'
                )
                expect(actions.showVariableSelectModal).not.toHaveBeenCalled()
            }
        )

        it('asks for events first when the template has variables', () => {
            const template = makeTemplate('team', { variables: [EVENT_VARIABLE] })
            const actions = mountTable({ isStaff: false, templates: [template] })

            fireEvent.click(screen.getByText('New dashboard from template'))

            expect(actions.showVariableSelectModal).toHaveBeenCalledWith(template)
            expect(actions.createDashboardFromTemplate).not.toHaveBeenCalled()
        })

        it('does nothing while another dashboard is being created', () => {
            const actions = mountTable({
                isStaff: false,
                templates: [makeTemplate('team')],
                dashboardCreationLoading: true,
            })

            fireEvent.click(screen.getByText('New dashboard from template'))

            expect(actions.setIsLoading).not.toHaveBeenCalled()
            expect(actions.createDashboardFromTemplate).not.toHaveBeenCalled()
        })
    })

    describe('templates the viewer cannot manage', () => {
        it('shows an organization template from another project as read-only, naming the owning project', () => {
            mountTable({ isStaff: false, templates: [makeTemplate('organization', { team_id: OTHER_TEAM.id })] })

            expect(screen.getByLabelText('Managed in Marketing site')).toBeInTheDocument()
            expect(document.querySelector('[data-attr="dashboard-template-name-edit"]')).not.toBeInTheDocument()
            expect(screen.queryByText('New dashboard from template')).not.toBeInTheDocument()
        })

        it('gives viewers without editor access a read-only list', () => {
            ;(userHasAccess as jest.Mock).mockReturnValue(false)
            mountTable({ isStaff: false, templates: [makeTemplate('team')] })

            expect(document.querySelector('[data-attr="dashboard-template-name-edit"]')).not.toBeInTheDocument()
            expect(screen.queryByText('Edit')).not.toBeInTheDocument()
        })
    })

    it.each([
        { label: 'staff', isStaff: true, showsOfficialFilter: true },
        { label: 'customers', isStaff: false, showsOfficialFilter: false },
    ])('only offers the Official filter to staff ($label)', ({ isStaff, showsOfficialFilter }) => {
        mountTable({ isStaff, templates: [makeTemplate('team')] })

        expect(document.querySelector('[data-attr="dashboard-templates-filter-official"]') !== null).toBe(
            showsOfficialFilter
        )
    })

    describe('empty states', () => {
        it('explains how to add a template when there are none', () => {
            mountTable({ isStaff: false, templates: [] })

            expect(screen.getByText('No templates yet')).toBeInTheDocument()
            expect(screen.getByText('Browse PostHog templates')).toBeInTheDocument()
        })

        it('clears the search and filter when a search matches nothing', () => {
            const actions = mountTable({ isStaff: false, templates: [], searchText: 'churn' })

            expect(screen.getByText('No templates match "churn"')).toBeInTheDocument()
            fireEvent.click(screen.getByText('Clear filters'))

            expect(actions.setTemplateFilter).toHaveBeenCalledWith('')
            expect(actions.setTemplatesTabVisibility).toHaveBeenCalledWith('all')
        })
    })
})
