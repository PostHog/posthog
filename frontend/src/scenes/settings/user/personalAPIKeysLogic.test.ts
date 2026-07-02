import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { themeLogic } from '~/layout/navigation/themeLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

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
})
