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
        expect(screen.queryByText(/keeps working/)).not.toBeInTheDocument()
    })

    it('never renders the plaintext key for teams that still have one', () => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            secret_api_token: 'phs_legacy_primary_token_value',
            secret_api_token_backup: 'phs_legacy_backup_token_value',
        })

        render(<FlagsSecureApiKeys />)

        expect(screen.getByText('Create a project secret API key')).toBeInTheDocument()
        expect(screen.getByText(/keeps working/)).toBeInTheDocument()
        expect(screen.queryByText('phs_legacy_primary_token_value', { exact: false })).not.toBeInTheDocument()
        expect(screen.queryByText('phs_legacy_backup_token_value', { exact: false })).not.toBeInTheDocument()
    })
})
