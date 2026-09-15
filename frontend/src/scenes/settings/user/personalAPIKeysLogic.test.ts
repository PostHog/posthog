import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { timeSensitiveAuthenticationLogic } from 'lib/components/TimeSensitiveAuthentication/timeSensitiveAuthenticationLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { PersonalAPIKeyType } from '~/types'

import { personalAPIKeysLogic } from './personalAPIKeysLogic'

describe('personalAPIKeysLogic', () => {
    let logic: ReturnType<typeof personalAPIKeysLogic.build>
    let capturedCreatePayload: any = null

    beforeEach(() => {
        capturedCreatePayload = null

        useMocks({
            get: {
                '/api/personal_api_keys/': [],
                '/api/projects/': { results: [], count: 0, next: null, previous: null },
            },
            post: {
                '/api/personal_api_keys/': async ({ request }) => {
                    capturedCreatePayload = await request.json()
                    return [
                        200,
                        {
                            id: 'new-key-id',
                            label: capturedCreatePayload?.label,
                            scopes: capturedCreatePayload?.scopes,
                            scoped_organizations: capturedCreatePayload?.scoped_organizations ?? [],
                            scoped_teams: capturedCreatePayload?.scoped_teams ?? [],
                            value: 'phx_test',
                        },
                    ]
                },
                '/api/personal_api_keys/:id/roll/': () => [
                    200,
                    { id: 'key-to-roll', label: 'Roller', scopes: ['*'], value: 'phx_rolled' },
                ],
            },
        })

        initKeaTests()
        featureFlagLogic.mount()
        userLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        // createKeySuccess opens a LemonDialog with a CodeSnippet, which reads themeLogic.
        themeLogic.mount()

        logic = personalAPIKeysLogic()
        logic.mount()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it('strips llm_gateway scopes from create payload when GATEWAY_PERSONAL_API_KEY flag is disabled', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})

        logic.actions.setEditingKeyId('new')
        logic.actions.setEditingKeyValues({
            label: 'Test key',
            access_type: 'all',
            scopes: ['feature_flag:read', 'llm_gateway:read', 'insight:write'],
        })

        await logic.asyncActions.submitEditingKey()
        // The form submit's API call settles asynchronously under MSW v2 — drain it
        await expectLogic(logic).toFinishAllListeners()

        expect(capturedCreatePayload).not.toBeNull()
        expect(capturedCreatePayload.scopes).toEqual(['feature_flag:read', 'insight:write'])
        expect(capturedCreatePayload.scopes).not.toContain('llm_gateway:read')
    })

    it('preserves llm_gateway scopes from create payload when GATEWAY_PERSONAL_API_KEY flag is enabled', async () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.GATEWAY_PERSONAL_API_KEY], {
            [FEATURE_FLAGS.GATEWAY_PERSONAL_API_KEY]: true,
        })

        logic.actions.setEditingKeyId('new')
        logic.actions.setEditingKeyValues({
            label: 'Test key',
            access_type: 'all',
            scopes: ['feature_flag:read', 'llm_gateway:read'],
        })

        await logic.asyncActions.submitEditingKey()
        // The form submit's API call settles asynchronously under MSW v2 — drain it
        await expectLogic(logic).toFinishAllListeners()

        expect(capturedCreatePayload).not.toBeNull()
        expect(capturedCreatePayload.scopes).toEqual(['feature_flag:read', 'llm_gateway:read'])
    })

    it('preserves the `*` (all access) scope regardless of flag state', async () => {
        featureFlagLogic.actions.setFeatureFlags([], {})

        logic.actions.setEditingKeyId('new')
        logic.actions.setEditingKeyValues({
            label: 'Test key',
            access_type: 'all',
            scopes: ['*'],
        })

        await logic.asyncActions.submitEditingKey()
        // The form submit's API call settles asynchronously under MSW v2 — drain it
        await expectLogic(logic).toFinishAllListeners()

        expect(capturedCreatePayload).not.toBeNull()
        expect(capturedCreatePayload.scopes).toEqual(['*'])
    })

    it.each(['survey', 'early_access_feature'])(
        'auto-selects feature_flag:write when %s write is granted',
        async (scope) => {
            logic.actions.setEditingKeyId('new')
            logic.actions.setScopeRadioValue(scope, 'write')
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.editingKey.scopes).toContain(`${scope}:write`)
            expect(logic.values.editingKey.scopes).toContain('feature_flag:write')
        }
    )

    it('leaves the auto-selected feature_flag:write removable', async () => {
        logic.actions.setEditingKeyId('new')
        logic.actions.setScopeRadioValue('survey', 'write')
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setScopeRadioValue('feature_flag', 'none')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.editingKey.scopes).toContain('survey:write')
        expect(logic.values.editingKey.scopes).not.toContain('feature_flag:write')
    })

    it('surfaces an error when a created key arrives without a value to copy', async () => {
        const errorSpy = jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)

        logic.actions.createKeySuccess({ id: 'x', label: 'X', scopes: ['*'] } as PersonalAPIKeyType)
        await expectLogic(logic).toFinishAllListeners()

        expect(errorSpy).toHaveBeenCalledTimes(1)
    })

    it.each([
        [
            'a created key',
            (): void =>
                logic.actions.createKeySuccess({
                    id: 'x',
                    label: 'X',
                    scopes: ['*'],
                    value: 'phx_secret',
                } as PersonalAPIKeyType),
        ],
        [
            'a rolled key',
            (): void =>
                logic.actions.showRollKeySuccessDialog(
                    { id: 'x', label: 'X', scopes: ['*'], value: 'phx_secret' } as PersonalAPIKeyType,
                    'phx_...abcd'
                ),
        ],
    ])('reveals %s in a dialog that blocks overlay dismissal of the secret', async (_name, reveal) => {
        const openSpy = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})

        reveal()
        await expectLogic(logic).toFinishAllListeners()

        expect(openSpy).toHaveBeenCalledWith(expect.objectContaining({ hasUnsavedInput: true }))
    })

    it('checks for re-authentication before rolling a key', async () => {
        userLogic.actions.loadUserSuccess({
            ...MOCK_DEFAULT_USER,
            sensitive_session_expires_at: dayjs().add(1, 'hour').toISOString(),
        })
        apiStatusLogic.mount()
        timeSensitiveAuthenticationLogic.mount()
        logic.actions.loadKeysSuccess([
            { id: 'key-to-roll', label: 'Roller', scopes: ['*'], mask_value: 'phx_...abcd' } as PersonalAPIKeyType,
        ])

        await expectLogic(timeSensitiveAuthenticationLogic, () => {
            logic.actions.rollKey('key-to-roll')
        }).toDispatchActions(['checkReauthentication'])
    })

    it.each([
        ['sensitive_action_required_reauth', 1],
        ['server_error', 0],
    ])('toasts a roll failure only for the re-auth 403 (code %s)', async (code, expectedToasts) => {
        const errorSpy = jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)

        logic.actions.rollKeyFailure('failed', { code, status: code === 'server_error' ? 500 : 403 })
        await expectLogic(logic).toFinishAllListeners()

        expect(errorSpy).toHaveBeenCalledTimes(expectedToasts)
    })
})
