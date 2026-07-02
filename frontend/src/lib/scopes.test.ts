import { AGENT_USE_CASE_SCOPES } from 'lib/agentScopes.generated'
import { AGENT_CLI_API_KEY_SCOPES, API_KEY_SCOPE_PRESETS, API_SCOPES } from 'lib/scopes'

const getRenderableKeyCreationScopes = (): Set<string> =>
    new Set(
        API_SCOPES.flatMap(({ key, disabledActions }) =>
            (['read', 'write'] as const)
                .filter((action) => !disabledActions?.includes(action))
                .map((action) => `${key}:${action}`)
        )
    )

describe('API_KEY_SCOPE_PRESETS', () => {
    const findPreset = (value: string): (typeof API_KEY_SCOPE_PRESETS)[number] => {
        const preset = API_KEY_SCOPE_PRESETS.find((p) => p.value === value)
        if (!preset) {
            throw new Error(`Preset "${value}" not found`)
        }
        return preset
    }

    describe('read_only_access', () => {
        it('exists with the expected label', () => {
            const preset = findPreset('read_only_access')
            expect(preset.label).toBe('Read-only access')
        })

        it('contains :read for every entry in API_SCOPES except unprivileged-excluded scopes', () => {
            const preset = findPreset('read_only_access')
            const expected = API_SCOPES.filter(({ unprivilegedExcluded }) => !unprivilegedExcluded)
                .map(({ key }) => `${key}:read`)
                .sort()
            expect([...preset.scopes].sort()).toEqual(expected)
            expect(preset.scopes).not.toContain('llm_gateway:read')
        })
    })

    describe('all_access', () => {
        it('still uses the wildcard scope', () => {
            const preset = findPreset('all_access')
            expect(preset.scopes).toEqual(['*'])
        })
    })

    describe('agent_cli', () => {
        it('exists separately from the MCP server preset', () => {
            expect(findPreset('mcp_server').label).toBe('MCP Server')

            const preset = findPreset('agent_cli')
            expect(preset.label).toBe('Agent CLI')
            expect(preset.access_type).toBe('all')
        })

        it('uses the generated Agent CLI scopes with key-disabled writes removed', () => {
            const preset = findPreset('agent_cli')
            expect(preset.scopes).toEqual(AGENT_CLI_API_KEY_SCOPES)
            expect(preset.scopes).toEqual(
                expect.arrayContaining(['user:read', 'project:read', 'query:read', 'insight:write'])
            )
            expect(preset.scopes).not.toContain('file_system:write')
            expect(preset.scopes).not.toContain('integration:write')
            expect(preset.scopes).not.toContain('user:write')
        })

        it('only includes scopes the key creation UI can render', () => {
            const renderableScopes = getRenderableKeyCreationScopes()

            expect(AGENT_CLI_API_KEY_SCOPES).toEqual(
                (AGENT_USE_CASE_SCOPES as readonly string[]).filter((scope) => renderableScopes.has(scope))
            )
            expect(AGENT_CLI_API_KEY_SCOPES.every((scope) => renderableScopes.has(scope))).toBe(true)
        })
    })
})
