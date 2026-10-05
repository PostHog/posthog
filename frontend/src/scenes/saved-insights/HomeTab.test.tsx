import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { HomeTab } from './HomeTab'

jest.mock('./HomeTabDefault', () => ({
    HomeTabDefault: () => <div>PostHog Home</div>,
}))
jest.mock('scenes/dashboard/Dashboard', () => ({
    Dashboard: ({ id }: { id: string }) => <div>Home dashboard {id}</div>,
}))

describe('HomeTab', () => {
    afterEach(cleanup)

    it.each([
        ['the opinionated Home dashboard', null, 'PostHog Home'],
        ['a selected Home dashboard', 42, 'Home dashboard 42'],
    ])('renders %s', (_scenario, existingDashboardId, expectedContent) => {
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            home_tab_dashboard: existingDashboardId,
        })

        render(<HomeTab />)
        expect(screen.getByText(expectedContent)).toBeInTheDocument()
    })
})
