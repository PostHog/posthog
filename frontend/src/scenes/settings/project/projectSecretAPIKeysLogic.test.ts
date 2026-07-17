import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { projectSecretAPIKeysLogic } from './projectSecretAPIKeysLogic'

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
})
