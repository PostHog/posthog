import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { LemonDialog } from '@posthog/lemon-ui'

import api from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { ProjectSecretAPIKeyApi } from '~/generated/core/api.schemas'
import { initKeaTests } from '~/test/init'

import { ProjectSecretAPIKeys } from './ProjectSecretAPIKeys'
import {
    EditingProjectKeyFormValues,
    MAX_PROJECT_API_KEYS_PER_PROJECT,
    projectSecretAPIKeysLogic,
} from './projectSecretAPIKeysLogic'

const createKeys = (count: number): ProjectSecretAPIKeyApi[] =>
    Array.from({ length: count }, (_, index) => ({
        id: String(index),
        label: `Key ${index}`,
        value: '',
        mask_value: null,
        created_at: '2026-01-01T00:00:00Z',
        created_by: {
            id: 1,
            uuid: 'test-user',
            first_name: 'Test',
            email: 'test@example.com',
            hedgehog_config: null,
        },
        last_used_at: null,
        last_rolled_at: null,
        scopes: ['endpoint:read'],
        ai_credential: null,
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
        jest.restoreAllMocks()
    })

    it.each([
        { scopes: ['llm_gateway:read'], expectsConfirmation: true },
        { scopes: ['endpoint:read'], expectsConfirmation: false },
    ])(
        'asks to confirm a new key only when it has the AI gateway scope: $scopes',
        async ({ scopes, expectsConfirmation }) => {
            const create = jest.spyOn(api.projectSecretApiKeys, 'create').mockResolvedValue(createKeys(1)[0])
            const dialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
            logic.actions.setEditingKeyId('new')
            logic.actions.setEditingKeyValues({
                label: 'Gateway',
                scopes: scopes as EditingProjectKeyFormValues['scopes'],
            })

            await logic.asyncActions.submitEditingKey()

            expect(dialog).toHaveBeenCalledTimes(expectsConfirmation ? 1 : 0)
            expect(create).toHaveBeenCalledTimes(expectsConfirmation ? 0 : 1)
            if (expectsConfirmation) {
                logic.actions.confirmGatewayScope()
                await logic.asyncActions.submitEditingKey()
                expect(create).toHaveBeenCalledWith(expect.objectContaining({ scopes: ['llm_gateway:read'] }))
            }
        }
    )

    it.each([
        { dialog: 'created', show: (key: ProjectSecretAPIKeyApi) => logic.actions.createKeySuccess(key) },
        { dialog: 'rolled', show: (key: ProjectSecretAPIKeyApi) => logic.actions.showRollKeySuccessDialog(key) },
    ])('hides the $dialog key value from session replay and autocapture', ({ show }) => {
        const dialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
        const key = { ...createKeys(1)[0], value: 'phs_fixture_key_value' }

        show(key)

        expect(dialog).toHaveBeenCalledTimes(1)
        render(<>{dialog.mock.calls[0][0].content}</>)
        expect(screen.getByText(key.value).closest('.ph-no-capture')).not.toBeNull()
    })

    it.each([
        {
            description: 'below the backend limit',
            keyCount: MAX_PROJECT_API_KEYS_PER_PROJECT - 1,
            expectedDisabled: false,
        },
        {
            description: 'at the backend limit',
            keyCount: MAX_PROJECT_API_KEYS_PER_PROJECT,
            expectedDisabled: true,
        },
    ])('sets creation availability $description', ({ keyCount, expectedDisabled }) => {
        logic.actions.loadKeysSuccess(createKeys(keyCount))
        render(<ProjectSecretAPIKeys />)

        const button = screen.getByText('Create project secret API key').closest('button')
        if (expectedDisabled) {
            expect(button).toHaveAttribute('aria-disabled', 'true')
        } else {
            expect(button).not.toHaveAttribute('aria-disabled', 'true')
        }
    })
})
