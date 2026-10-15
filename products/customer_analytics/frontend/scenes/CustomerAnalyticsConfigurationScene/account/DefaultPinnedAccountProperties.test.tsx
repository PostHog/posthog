import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { DefaultPinnedAccountProperties } from './DefaultPinnedAccountProperties'
import { defaultPinnedAccountPropertiesLogic } from './defaultPinnedAccountPropertiesLogic'

const CUSTOM_PROPERTIES_URL = '/api/projects/:team_id/custom_property_definitions/'
const RELATIONSHIPS_URL = '/api/projects/:team_id/account_relationship_definitions/'

describe('DefaultPinnedAccountProperties', () => {
    const logic = defaultPinnedAccountPropertiesLogic()

    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                [CUSTOM_PROPERTIES_URL]: { count: 0, results: [] },
                [RELATIONSHIPS_URL]: { count: 0, results: [] },
            },
        })
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: OrganizationMembershipLevel.Member,
        })
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
        teamLogic.unmount()
    })

    it('disables project default changes for non-admins', async () => {
        render(<DefaultPinnedAccountProperties />)

        const button = screen.getByText('Configure defaults').closest('button')
        await waitFor(() => expect(button).toHaveAttribute('aria-disabled', 'true'))
    })
})
