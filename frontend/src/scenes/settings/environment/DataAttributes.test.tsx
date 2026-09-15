import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { DataAttributes } from './DataAttributes'

describe('<DataAttributes />', () => {
    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
    })

    afterEach(() => cleanup())

    it.each([
        { description: 'a list of strings', dataAttributes: ['data-attr'] },
        { description: 'a string the API accepted before it validated the field', dataAttributes: 'data-attr' },
        { description: 'null', dataAttributes: null },
    ])('renders the select when the team holds $description', ({ dataAttributes }) => {
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: OrganizationMembershipLevel.Admin,
            data_attributes: dataAttributes as string[],
        })

        render(<DataAttributes />)

        expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
    })
})
