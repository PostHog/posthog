import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { DataAttributes } from './DataAttributes'

describe('<DataAttributes />', () => {
    const loadTeam = (dataAttributes: unknown): void =>
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: OrganizationMembershipLevel.Admin,
            data_attributes: dataAttributes as string[],
        })

    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
    })

    afterEach(() => cleanup())

    it.each([
        { description: 'a list of strings', dataAttributes: ['data-attr'] },
        { description: 'a string the API accepted before it validated the field', dataAttributes: 'data-attr' },
        { description: 'a list holding a value that is not a string', dataAttributes: ['data-attr', 1] },
        { description: 'null', dataAttributes: null },
    ])('renders the select when the team holds $description', ({ dataAttributes }) => {
        loadTeam(dataAttributes)

        render(<DataAttributes />)

        expect(screen.getByText('Save')).toBeInTheDocument()
    })

    it('saves only the strings when the team holds a list with a value that is not a string', () => {
        const updateCurrentTeam = jest.spyOn(teamLogic.actions, 'updateCurrentTeam').mockReturnValue(undefined)
        loadTeam(['data-attr', 1])

        render(<DataAttributes />)
        fireEvent.click(screen.getByText('Save'))

        expect(updateCurrentTeam).toHaveBeenCalledWith({ data_attributes: ['data-attr'] })
    })
})
