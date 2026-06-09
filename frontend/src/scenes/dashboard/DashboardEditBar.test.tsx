import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { groupsModel } from '~/models/groupsModel'
import { DashboardMode } from '~/types'

import { DashboardEditBar } from './DashboardEditBar'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: jest.fn(),
    BindLogic: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

jest.mock('scenes/dashboard/dashboardLogic', () => ({
    dashboardLogic: { __mock: 'dashboardLogic' },
}))

jest.mock('scenes/insights/insightLogic', () => ({
    insightLogic: { __mock: 'insightLogic' },
}))

jest.mock('~/models/groupsModel', () => ({
    groupsModel: { __mock: 'groupsModel' },
}))

jest.mock('lib/utils/getAppContext', () => ({
    getProjectEventExistence: () => ({ hasPageview: true, hasScreen: false }),
}))

jest.mock('lib/components/AppShortcuts/AppShortcut', () => ({
    AppShortcut: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

jest.mock('lib/components/DateFilter/DateFilter', () => ({
    DateFilter: () => <div data-attr="date-filter" />,
}))

jest.mock('lib/components/PropertyFilters/PropertyFilters', () => ({
    PropertyFilters: () => <div data-attr="property-filters" />,
}))

jest.mock('scenes/insights/filters/BreakdownFilter/TaxonomicBreakdownFilter', () => ({
    TaxonomicBreakdownFilter: () => <div data-attr="breakdown-filter" />,
}))

jest.mock('~/queries/nodes/DataVisualization/Components/Variables/Variables', () => ({
    VariablesForDashboard: () => <div data-attr="dashboard-variables" />,
}))

const mockedUseValues = useValues as jest.Mock
const mockedUseActions = useActions as jest.Mock

describe('DashboardEditBar', () => {
    afterEach(() => {
        cleanup()
    })

    const setupMocks = (canEditDashboard: boolean): void => {
        jest.clearAllMocks()

        mockedUseValues.mockImplementation((logic) => {
            if (logic === dashboardLogic) {
                return {
                    dashboard: { id: 5 },
                    dashboardMode: null as DashboardMode | null,
                    hasVariables: false,
                    effectiveEditBarFilters: { properties: [], breakdown_filter: null },
                    canEditDashboard,
                }
            }
            if (logic === groupsModel) {
                return { groupsTaxonomicTypes: [] }
            }
            if (logic === insightLogic) {
                return {}
            }
            return {}
        })

        mockedUseActions.mockReturnValue({
            setDates: jest.fn(),
            setProperties: jest.fn(),
            setBreakdownFilter: jest.fn(),
            setDashboardMode: jest.fn(),
        })
    }

    it.each([
        { canEditDashboard: true, expectEditControls: true },
        { canEditDashboard: false, expectEditControls: false },
    ])(
        'shows the date filter always and gates filter/breakdown controls on canEditDashboard=$canEditDashboard',
        ({ canEditDashboard, expectEditControls }) => {
            setupMocks(canEditDashboard)
            render(<DashboardEditBar />)

            // The date filter only previews via URL params, so viewers keep it.
            expect(screen.getByTestId('date-filter')).toBeInTheDocument()

            if (expectEditControls) {
                expect(screen.getByTestId('property-filters')).toBeInTheDocument()
                expect(screen.getByTestId('breakdown-filter')).toBeInTheDocument()
            } else {
                expect(screen.queryByTestId('property-filters')).not.toBeInTheDocument()
                expect(screen.queryByTestId('breakdown-filter')).not.toBeInTheDocument()
            }
        }
    )
})
