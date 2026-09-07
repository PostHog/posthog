import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { ProjectSecretAPIKeyApi } from '~/generated/core/api.schemas'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { projectSecretAPIKeysLogic } from './projectSecretAPIKeysLogic'

const KEY_PATH = '/api/projects/:team_id/project_secret_api_keys/:id/'
const STALE_KEY = { id: 'stale', label: 'Stale' } as ProjectSecretAPIKeyApi
const LIVE_KEY = { id: 'live', label: 'Live' } as ProjectSecretAPIKeyApi

describe('projectSecretAPIKeysLogic', () => {
    let logic: ReturnType<typeof projectSecretAPIKeysLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                // api.projectSecretApiKeys.list() reads `.results` off a paginated response
                '/api/projects/:team_id/project_secret_api_keys/': { results: [] },
            },
        })

        initKeaTests()
        featureFlagLogic.mount()

        logic = projectSecretAPIKeysLogic()
        logic.mount()
    })

    it.each([
        ['disabled', false],
        ['enabled', true],
    ])('gates the llm_gateway scope and preset on the AI_GATEWAY flag (%s)', (_label, flagEnabled) => {
        featureFlagLogic.actions.setFeatureFlags(
            flagEnabled ? [FEATURE_FLAGS.AI_GATEWAY] : [],
            flagEnabled ? { [FEATURE_FLAGS.AI_GATEWAY]: true } : {}
        )

        const scopeKeys = logic.values.filteredScopes.map(({ key }) => key)
        const presetValues = logic.values.availablePresets.map(({ value }) => value)

        expect(scopeKeys.includes('llm_gateway')).toBe(flagEnabled)
        expect(presetValues.includes('llm_gateway')).toBe(flagEnabled)

        // endpoint access is always available regardless of the flag
        expect(scopeKeys).toContain('endpoint')
        expect(presetValues).toContain('endpoint_execution')
    })

    it('labels the llm_gateway scope as "AI gateway" and keeps it read-only when the flag is enabled', () => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.AI_GATEWAY], {
            [FEATURE_FLAGS.AI_GATEWAY]: true,
        })

        const gatewayScope = logic.values.filteredScopes.find(({ key }) => key === 'llm_gateway')

        expect(gatewayScope).not.toBeUndefined()
        expect(gatewayScope?.label).toBe('AI gateway')
        expect(gatewayScope?.disabledActions).toContain('write')
    })

    describe('a key that another tab already deleted', () => {
        beforeEach(async () => {
            // The mount load resolves with an empty list, so seed the table only once it settles.
            await expectLogic(logic).toFinishAllListeners()
            useMocks({
                delete: { [KEY_PATH]: () => [404, { detail: 'Not found.' }] },
                patch: { [KEY_PATH]: () => [404, { detail: 'Not found.' }] },
                post: { [`${KEY_PATH}roll/`]: () => [404, { detail: 'Not found.' }] },
            })
            logic.actions.loadKeysSuccess([STALE_KEY, LIVE_KEY])
        })

        // A 404 here is the state the user asked for, or a row they can no longer act on. Both
        // recover in the logic, so neither may reach the loader failure that error tracking reads.
        it.each([
            ['deleteKey', 'deleteKeyFailure', () => logic.actions.deleteKey(STALE_KEY.id)],
            ['rollKey', 'rollKeyFailure', () => logic.actions.rollKey(STALE_KEY.id)],
            [
                'submitEditingKey',
                'submitEditingKeyFailure',
                () => {
                    logic.actions.setEditingKeyId(STALE_KEY.id)
                    logic.actions.setEditingKeyValues({ label: 'Renamed', scopes: ['endpoint:read'] })
                    logic.actions.submitEditingKey()
                },
            ],
        ])('drops its row and reports no failure when %s gets a 404', async (_name, failureAction, trigger) => {
            const errorToast = jest.spyOn(lemonToast, 'error').mockImplementation()

            await expectLogic(logic, trigger).toFinishAllListeners().toNotHaveDispatchedActions([failureAction])

            expect(logic.values.keys).toEqual([LIVE_KEY])
            expect(errorToast).not.toHaveBeenCalledWith(expect.stringContaining('Failed to'))
        })
    })
})
