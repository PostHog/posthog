import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { setReadOnlyGetter, setReadOnlyNotifier } from 'lib/readOnlyGuard'
import { userLogic } from 'scenes/userLogic'

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
                '/api/personal_api_keys/': async (req) => {
                    capturedCreatePayload = await req.json()
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

        expect(capturedCreatePayload).not.toBeNull()
        expect(capturedCreatePayload.scopes).toEqual(['*'])
    })

    describe('in read-only mode', () => {
        // Register the guard so api.ts throws ReadOnlyModeError on writes, like
        // selfReadOnlyModeLogic does in production. The UI gates these triggers
        // separately — this verifies the defense-in-depth swallow for any future
        // call site that forgets the UI guard.
        beforeEach(() => {
            setReadOnlyGetter(() => true)
            setReadOnlyNotifier(() => {})
        })

        afterEach(() => {
            setReadOnlyGetter(null)
            setReadOnlyNotifier(null)
        })

        it('swallows ReadOnlyModeError on rollKey without surfacing it', async () => {
            // rollKey only attempts the API call if the key is already in state.
            logic.actions.loadKeysSuccess([
                {
                    id: 'some-key-id',
                    label: 'Existing key',
                    scopes: ['feature_flag:read'],
                    mask_value: 'phx_***',
                } as any,
            ])
            await expect(logic.asyncActions.rollKey('some-key-id')).resolves.toBeUndefined()
        })

        it('swallows ReadOnlyModeError on deleteKey without surfacing it', async () => {
            await expect(logic.asyncActions.deleteKey('some-key-id')).resolves.toBeUndefined()
        })

        it('swallows ReadOnlyModeError on create submit without surfacing it', async () => {
            featureFlagLogic.actions.setFeatureFlags([], {})

            logic.actions.setEditingKeyId('new')
            logic.actions.setEditingKeyValues({
                label: 'Test key',
                access_type: 'all',
                scopes: ['feature_flag:read'],
            })

            await expect(logic.asyncActions.submitEditingKey()).resolves.toBeUndefined()
            expect(capturedCreatePayload).toBeNull()
        })
    })
})
