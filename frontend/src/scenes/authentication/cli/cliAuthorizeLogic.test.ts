import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { AGENT_USE_CASE_SCOPES } from 'lib/agentScopes.generated'
import { API_SCOPES } from 'lib/scopes'

import { initKeaTests } from '~/test/init'

import { CLI_SCOPE_PRESETS, cliAuthorizeLogic } from './cliAuthorizeLogic'

const getRenderableKeyCreationScopes = (): Set<string> =>
    new Set(
        API_SCOPES.flatMap(({ key, disabledActions }) =>
            (['read', 'write'] as const)
                .filter((action) => !disabledActions?.includes(action))
                .map((action) => `${key}:${action}`)
        )
    )

describe('cliAuthorizeLogic', () => {
    let logic: ReturnType<typeof cliAuthorizeLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = cliAuthorizeLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('grants the MCP scope set for the agent-cli use case, minus key-disabled writes', async () => {
        router.actions.push('/cli/authorize', {
            code: 'ABCD-1234',
            use_cases: 'agent-cli',
        })

        await expectLogic(logic).toMatchValues({
            requestedUseCases: ['agent-cli'],
        })
        const scopes = logic.values.authorize.scopes
        // Covers the agent surface (reads + the writes that are allowed on a key)
        expect(scopes).toEqual(expect.arrayContaining(['user:read', 'project:read', 'query:read', 'insight:write']))
        // But drops writes the product withholds from manually-created keys
        expect(scopes).not.toContain('file_system:write')
        expect(scopes).not.toContain('integration:write')
        expect(scopes).not.toContain('user:write')
        // Faithful subset of the generated MCP mirror
        expect(scopes.every((scope) => (AGENT_USE_CASE_SCOPES as readonly string[]).includes(scope))).toBe(true)
        // No hidden grants: every submitted Agent CLI scope must have a visible UI row
        const renderableScopes = getRenderableKeyCreationScopes()
        expect(scopes.every((scope) => renderableScopes.has(scope))).toBe(true)
    })

    it('filters out unknown use cases from the URL', async () => {
        router.actions.push('/cli/authorize', {
            code: 'ABCD-1234',
            use_cases: 'agent-cli,bogus,schema',
        })

        await expectLogic(logic).toMatchValues({
            requestedUseCases: ['agent-cli', 'schema'],
        })
    })

    it('normalizes the legacy agent use case from older CLI links', async () => {
        router.actions.push('/cli/authorize', {
            code: 'ABCD-1234',
            use_cases: 'agent,schema',
        })

        await expectLogic(logic).toMatchValues({
            requestedUseCases: ['agent-cli', 'schema'],
        })
    })

    it('defaults to the agent-cli use case when none are specified', async () => {
        router.actions.push('/cli/authorize', { code: 'ABCD-1234' })

        await expectLogic(logic).toMatchValues({
            requestedUseCases: ['agent-cli'],
        })
        expect(logic.values.authorize.scopes).toEqual(
            expect.arrayContaining(['user:read', 'project:read', 'query:read'])
        )
        expect(logic.values.authorize.scopes).not.toContain('file_system:write')
    })

    it('reflects the matching preset for the current scope selection', async () => {
        router.actions.push('/cli/authorize', { code: 'ABCD-1234' })

        // Default agent scopes map onto the agent-cli preset
        await expectLogic(logic).toMatchValues({ scopePreset: 'agent-cli' })
        expect(CLI_SCOPE_PRESETS.find((preset) => preset.value === 'agent-cli')?.label).toBe('Agent CLI')

        // Selecting a preset replaces the scope set and updates the dropdown
        logic.actions.setScopePreset('error_tracking')
        await expectLogic(logic).toMatchValues({
            scopePreset: 'error_tracking',
        })
        expect(logic.values.authorize.scopes).toEqual(['error_tracking:write'])

        expect(CLI_SCOPE_PRESETS.find((preset) => preset.value === 'all_access')).toBeUndefined()
        expect(CLI_SCOPE_PRESETS.find((preset) => preset.scopes.includes('*'))).toBeUndefined()
    })

    it('drops to a custom selection once a scope is fine-tuned', async () => {
        router.actions.push('/cli/authorize', { code: 'ABCD-1234' })
        await expectLogic(logic).toMatchValues({ scopePreset: 'agent-cli' })

        logic.actions.setScopeRadioValue('survey', 'none')
        await expectLogic(logic).toMatchValues({ scopePreset: null })
    })

    it('filters scopes by search term', async () => {
        router.actions.push('/cli/authorize', { code: 'ABCD-1234' })

        logic.actions.setSearchTerm('feature flag')
        await expectLogic(logic).toMatchValues({ searchTerm: 'feature flag' })
        expect(logic.values.filteredScopes.map((scope) => scope.key)).toContain('feature_flag')
        expect(logic.values.filteredScopes.every((scope) => scope.key === 'feature_flag')).toBe(true)
    })
})
