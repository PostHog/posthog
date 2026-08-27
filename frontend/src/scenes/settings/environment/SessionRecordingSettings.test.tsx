import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { ReplayGeneral } from './SessionRecordingSettings'

describe('ReplayGeneral', () => {
    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
        organizationLogic.mount()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows the restriction reason to a member who cannot toggle the switch', () => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: OrganizationMembershipLevel.Member,
        })
        render(<ReplayGeneral />)
        expect(screen.getByText(/restricted to project admins and up/i)).toBeInTheDocument()
    })

    it('hides the restriction reason from an admin', () => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: OrganizationMembershipLevel.Admin,
        })
        render(<ReplayGeneral />)
        expect(screen.queryByText(/restricted to project admins and up/i)).not.toBeInTheDocument()
    })
})
