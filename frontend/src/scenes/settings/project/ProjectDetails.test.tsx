import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { ProjectDetails } from './ProjectDetails'

describe('<ProjectDetails />', () => {
    beforeEach(() => {
        initKeaTests()
        organizationLogic.mount()
        organizationLogic.actions.loadCurrentOrganizationSuccess(MOCK_DEFAULT_ORGANIZATION)
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: OrganizationMembershipLevel.Admin,
        })
        projectLogic.mount()
        projectLogic.actions.loadCurrentProjectSuccess(MOCK_DEFAULT_PROJECT)
    })

    afterEach(() => {
        cleanup()
    })

    it('opens the tag editor from the Tags label, not only from the chip', async () => {
        render(<ProjectDetails />)

        await userEvent.click(screen.getByText('Tags'))

        expect(screen.getByTestId('new-tag-input')).toBeInTheDocument()
        // The label must follow the editor, or it goes dead again as soon as the trigger unmounts
        expect(screen.getByLabelText('Tags')).toHaveAttribute('data-attr', 'new-tag-input')
    })
})
