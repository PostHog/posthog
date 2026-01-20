import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'
import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'
import { Form } from 'kea-forms'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'
import type { CohortPropertyFilter, TeamType } from '~/types'

import { hogFunctionConfigurationLogic } from '../configuration/hogFunctionConfigurationLogic'
import { HogFunctionFilters } from './HogFunctionFilters'
import type { groupsModelType, teamLogicType } from './HogFunctionFilters.testType'

jest.mock('lib/hooks/useFeatureFlag', () => ({
    useFeatureFlag: jest.fn(() => false),
}))

jest.mock('scenes/teamLogic', () => {
    const { kea } = jest.requireActual('kea') as { kea: any }

    const teamLogic = kea({
        path: ['scenes', 'teamLogic'],
        actions: {
            loadCurrentTeamSuccess: (team: TeamType) => ({ team }),
        },
        reducers: {
            currentTeam: [
                null as TeamType | null,
                {
                    loadCurrentTeamSuccess: (_: TeamType | null, { team }: { team: TeamType }) => team,
                },
            ],
            currentTeamId: [
                null as number | null,
                {
                    loadCurrentTeamSuccess: (_: number | null, { team }: { team: TeamType }) => team?.id ?? null,
                },
            ],
        },
    }) as teamLogicType

    return { teamLogic }
})

jest.mock('kea-router', () => {
    const actual = jest.requireActual('kea-router')

    return {
        ...actual,
        router: {
            ...actual.router,
            values: {
                searchParams: {},
                hashParams: {},
                location: { pathname: '' },
            },
            actions: {
                replace: jest.fn(),
                push: jest.fn(),
            },
        },
    }
})

jest.mock('lib/components/TestAccountFiltersSwitch', () => ({
    TestAccountFilterSwitch: ({ disabled, disabledReason }: any) => (
        <button
            aria-label="Filter out internal and test users"
            data-disabled-reason={disabledReason ?? ''}
            disabled={disabled}
            role="switch"
            type="button"
        />
    ),
}))

jest.mock('scenes/max/MaxTool', () => ({
    __esModule: true,
    default: ({ children }: any) => (typeof children === 'function' ? children({ toolAvailable: false }) : children),
}))

jest.mock('lib/components/PropertyFilters/PropertyFilters', () => ({
    PropertyFilters: () => null,
}))

jest.mock('~/models/groupsModel', () => {
    const { kea } = jest.requireActual('kea') as { kea: any }

    const groupsModel = kea({
        path: ['models', 'groupsModel', 'mock'],
        selectors: {
            groupTypes: [() => [], () => new Map()],
            groupsTaxonomicTypes: [() => [], () => []],
        },
    }) as groupsModelType

    return { groupsModel }
})

jest.mock('scenes/insights/filters/ActionFilter/ActionFilter', () => ({
    ActionFilter: () => null,
}))

describe('HogFunctionFilters', () => {
    const cohortFilter: CohortPropertyFilter = {
        type: PropertyFilterType.Cohort,
        key: 'id',
        value: 123,
        operator: PropertyOperator.In,
    }

    const renderComponent = (filterTestAccounts: boolean): void => {
        cleanup()
        teamLogic.mount()
        const logicProps = { logicKey: `test-${filterTestAccounts}` }
        const logic = hogFunctionConfigurationLogic(logicProps)
        logic.mount()
        logic.actions.setConfigurationValue('type', 'destination')
        logic.actions.setConfigurationValue('filters', {
            source: 'events',
            filter_test_accounts: filterTestAccounts,
        })

        render(
            <BindLogic logic={hogFunctionConfigurationLogic} props={logicProps}>
                <Form logic={hogFunctionConfigurationLogic} props={logicProps} formKey="configuration">
                    <HogFunctionFilters />
                </Form>
            </BindLogic>
        )
    }

    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            test_account_filters: [cohortFilter],
        })
    })

    it.each([
        { filterTestAccounts: false, expectedDisabled: true },
        { filterTestAccounts: true, expectedDisabled: false },
    ])(
        'disables the test account filter switch when filter_test_accounts is $filterTestAccounts',
        ({ filterTestAccounts, expectedDisabled }) => {
            renderComponent(filterTestAccounts)

            const toggle = screen.getByRole('switch', { name: /filter out internal and test users/i })

            if (expectedDisabled) {
                expect(toggle).toBeDisabled()
                expect(toggle).toHaveAttribute(
                    'data-disabled-reason',
                    "Cohorts aren't supported in real-time filters. Remove cohorts from internal and test user filters to enable this."
                )
            } else {
                expect(toggle).not.toBeDisabled()
                expect(toggle).toHaveAttribute('data-disabled-reason', '')
            }
        }
    )
})
