import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'
import { ProjectSecretAPIKeyApi } from '~/types'

import { ProjectSecretAPIKeys } from './ProjectSecretAPIKeys'
import { MAX_PROJECT_API_KEYS_PER_PROJECT, projectSecretAPIKeysLogic } from './projectSecretAPIKeysLogic'

const createKeys = (count: number): ProjectSecretAPIKeyApi[] =>
    Array.from({ length: count }, (_, index) => ({
        id: String(index),
        label: `Key ${index}`,
        value: '',
        mask_value: null,
        created_at: '2026-01-01T00:00:00Z',
        created_by: { id: 1, uuid: 'test-user', first_name: 'Test', email: 'test@example.com' },
        last_used_at: null,
        last_rolled_at: null,
        scopes: ['endpoint:read'],
    }))

describe('<ProjectSecretAPIKeys />', () => {
    const logic = projectSecretAPIKeysLogic()

    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
        teamLogic.actions.loadCurrentTeamSuccess({
            ...MOCK_DEFAULT_TEAM,
            effective_membership_level: OrganizationMembershipLevel.Admin,
        })
        logic.mount()
    })

    afterEach(() => {
        cleanup()
        logic.unmount()
    })

    it('allows creation through the backend limit and blocks it at that limit', () => {
        logic.actions.loadKeysSuccess(createKeys(MAX_PROJECT_API_KEYS_PER_PROJECT - 1))
        const { unmount } = render(<ProjectSecretAPIKeys />)

        expect(screen.getByText('Create project secret API key').closest('button')).not.toHaveAttribute(
            'aria-disabled',
            'true'
        )

        unmount()
        logic.actions.loadKeysSuccess(createKeys(MAX_PROJECT_API_KEYS_PER_PROJECT))
        render(<ProjectSecretAPIKeys />)

        expect(screen.getByText('Create project secret API key').closest('button')).toHaveAttribute(
            'aria-disabled',
            'true'
        )
    })
})
