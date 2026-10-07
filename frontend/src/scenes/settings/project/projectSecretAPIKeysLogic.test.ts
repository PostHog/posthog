import { PROJECT_SECRET_API_KEY_SCOPE_PRESETS } from 'lib/scopes'

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

        logic = projectSecretAPIKeysLogic()
        logic.mount()
    })

    it('offers the llm_gateway scope read-only, labelled "AI gateway", with its preset', () => {
        const gatewayScope = logic.values.filteredScopes.find(({ key }) => key === 'llm_gateway')
        const presetValues = PROJECT_SECRET_API_KEY_SCOPE_PRESETS.map(({ value }) => value)

        expect(gatewayScope?.label).toBe('AI gateway')
        expect(gatewayScope?.disabledActions).toEqual(['write'])
        expect(presetValues).toContain('llm_gateway')
    })
})
