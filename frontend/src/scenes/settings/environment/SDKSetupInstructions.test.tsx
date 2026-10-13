import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { SDKSetupInstructions } from './SDKSetupInstructions'

describe('<SDKSetupInstructions />', () => {
    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM)
    })

    afterEach(() => {
        cleanup()
    })

    it('shows the initialize snippet with the project token for a server SDK', () => {
        render(<SDKSetupInstructions />)

        fireEvent.click(screen.getByText('Web'))
        fireEvent.click(screen.getByText('Python'))

        expect(screen.getByText('Install the package')).toBeInTheDocument()
        expect(screen.getByText('Initialize PostHog')).toBeInTheDocument()
        expect(screen.getByText(new RegExp(MOCK_DEFAULT_TEAM.api_token))).toBeInTheDocument()
    })
})
