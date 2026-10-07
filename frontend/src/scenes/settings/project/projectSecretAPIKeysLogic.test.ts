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

    it('offers no llm_gateway scope or preset', () => {
        const scopeKeys = logic.values.filteredScopes.map(({ key }) => key)
        const presetValues = PROJECT_SECRET_API_KEY_SCOPE_PRESETS.map(({ value }) => value)

        expect(scopeKeys).not.toContain('llm_gateway')
        expect(presetValues).not.toContain('llm_gateway')
        expect(scopeKeys).toContain('endpoint')
        expect(presetValues).toContain('endpoint_execution')
    })
})
