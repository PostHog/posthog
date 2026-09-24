import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { OrganizationMembershipLevel } from 'lib/constants'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { TeamDisplayName } from './TeamSettings'

describe('<TeamDisplayName />', () => {
    const loadProject = (name: string): void => {
        act(() => {
            projectLogic.actions.loadCurrentProjectSuccess({ ...MOCK_DEFAULT_PROJECT, name })
        })
    }

    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
        projectLogic.mount()
        organizationLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: OrganizationMembershipLevel.Admin,
        })
        organizationLogic.actions.loadCurrentOrganizationSuccess(MOCK_DEFAULT_ORGANIZATION)
    })

    afterEach(() => {
        cleanup()
    })

    it('follows the stored name while the field is untouched', () => {
        const { container } = render(<TeamDisplayName />)

        loadProject('Renamed elsewhere')

        expect(container.querySelector('input')).toHaveValue('Renamed elsewhere')
        expect(screen.getByText('Rename project').closest('button')).toHaveAttribute('aria-disabled', 'true')
    })

    it('keeps what the user typed when the project reloads', async () => {
        const { container } = render(<TeamDisplayName />)
        const input = container.querySelector('input') as HTMLInputElement

        await userEvent.clear(input)
        await userEvent.type(input, 'My new name')
        loadProject(MOCK_DEFAULT_PROJECT.name)

        expect(input).toHaveValue('My new name')
        expect(screen.getByText('Rename project').closest('button')).toHaveAttribute('aria-disabled', 'false')
    })
})
