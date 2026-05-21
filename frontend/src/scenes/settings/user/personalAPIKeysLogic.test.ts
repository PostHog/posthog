import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { type EditingKeyFormValues, personalAPIKeysLogic } from './personalAPIKeysLogic'

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

    describe('form validation', () => {
        type ValidationCase = {
            name: string
            values: Partial<EditingKeyFormValues>
            expectedErrors: Record<string, string | undefined>
        }

        const cases: ValidationCase[] = [
            {
                name: 'missing label',
                values: { label: '', access_type: 'all', scopes: ['feature_flag:read'] },
                expectedErrors: { label: 'Your personal API key needs a label' },
            },
            {
                name: 'empty scopes',
                values: { label: 'Test key', access_type: 'all', scopes: [] },
                expectedErrors: { scopes: 'Your personal API key needs at least one scope' },
            },
            {
                name: 'missing access type',
                values: { label: 'Test key', scopes: ['feature_flag:read'], access_type: undefined },
                expectedErrors: { access_type: 'Select access mode' },
            },
            {
                name: 'organization access without selected organizations',
                values: {
                    label: 'Test key',
                    access_type: 'organizations',
                    scopes: ['feature_flag:read'],
                    scoped_organizations: [],
                },
                expectedErrors: { scoped_organizations: 'Select at least one organization' },
            },
            {
                name: 'team access without selected teams',
                values: {
                    label: 'Test key',
                    access_type: 'teams',
                    scopes: ['feature_flag:read'],
                    scoped_teams: [],
                },
                expectedErrors: { scoped_teams: 'Select at least one project' },
            },
        ]

        cases.forEach(({ name, values, expectedErrors }) => {
            it(`surfaces a string error for: ${name}`, async () => {
                logic.actions.setEditingKeyId('new')
                logic.actions.setEditingKeyValues(values)

                await expectLogic(logic).toMatchValues({
                    editingKeyValidationErrors: expect.objectContaining(expectedErrors),
                })

                for (const message of Object.values(expectedErrors)) {
                    expect(typeof message).toBe('string')
                }

                // Submitting an invalid form should not call the API and should not throw.
                await expect(logic.asyncActions.submitEditingKey()).resolves.not.toThrow()
                expect(capturedCreatePayload).toBeNull()
            })
        })

        it('accepts a fully valid payload and clears all field errors', async () => {
            logic.actions.setEditingKeyId('new')
            logic.actions.setEditingKeyValues({
                label: 'Test key',
                access_type: 'all',
                scopes: ['feature_flag:read'],
            })

            await expectLogic(logic).toMatchValues({
                editingKeyValidationErrors: {
                    label: undefined,
                    scopes: undefined,
                    access_type: undefined,
                    scoped_organizations: undefined,
                    scoped_teams: undefined,
                },
            })
        })
    })
})
