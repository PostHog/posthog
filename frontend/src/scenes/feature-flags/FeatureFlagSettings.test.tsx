import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { FlagsSecureApiKeys } from './FeatureFlagSettings'

describe('<FlagsSecureApiKeys />', () => {
    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
    })

    afterEach(cleanup)

    it('directs teams without a legacy key to project secret API keys', () => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            secret_api_token: undefined,
            secret_api_token_backup: undefined,
        })

        render(<FlagsSecureApiKeys />)

        expect(screen.getByText('Create a project secret API key')).toBeInTheDocument()
        expect(screen.queryByText('Primary Key', { exact: false })).not.toBeInTheDocument()
    })
})
