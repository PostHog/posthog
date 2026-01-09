import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { ProjectAccountFiltersSetting } from './TestAccountFiltersConfig'

jest.mock('lib/components/PropertyFilters/PropertyFilters', () => ({
    PropertyFilters: () => null,
}))

jest.mock('~/models/cohortsModel', () => {
    const { kea } = jest.requireActual('kea')

    const cohortsModel = kea({
        path: ['models', 'cohortsModel', 'mock'],
        reducers: {
            cohortsById: [{}, {}],
        },
    })

    return { cohortsModel }
})

jest.mock('products/revenue_analytics/frontend/settings/revenueAnalyticsSettingsLogic', () => {
    const { kea } = jest.requireActual('kea')

    const revenueAnalyticsSettingsLogic = kea({
        path: ['scenes', 'data-management', 'revenue', 'revenueAnalyticsSettingsLogic', 'mock'],
        actions: {
            updateFilterTestAccounts: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
        },
        reducers: {
            filterTestAccounts: [
                false,
                {
                    updateFilterTestAccounts: (_, { filterTestAccounts }) => filterTestAccounts,
                },
            ],
        },
    })

    return { revenueAnalyticsSettingsLogic }
})

jest.mock('lib/utils/eventUsageLogic', () => {
    const { kea } = jest.requireActual('kea')

    const eventUsageLogic = kea({
        path: ['lib', 'utils', 'eventUsageLogic', 'mock'],
        actions: {
            reportTestAccountFiltersUpdated: (filters: any) => ({ filters }),
        },
    })

    return { eventUsageLogic }
})

describe('ProjectAccountFiltersSetting', () => {
    beforeEach(() => {
        initKeaTests()
        teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
    })

    it('explains that cohorts are not supported for real-time destinations', () => {
        render(<ProjectAccountFiltersSetting />)

        expect(screen.getByText(/add those properties directly here with an exclusive operator/i)).toBeInTheDocument()
        expect(screen.getByText(/cohorts can be useful for analytics queries/i)).toBeInTheDocument()
        expect(screen.getByText(/not supported in real-time destinations yet/i)).toBeInTheDocument()
    })
})
