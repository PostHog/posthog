import { AGENT_USE_CASE_SCOPES } from 'lib/agentScopes.generated'
import { AGENT_CLI_API_KEY_SCOPES, API_KEY_SCOPE_PRESETS, API_SCOPES, getScopeDescription } from 'lib/scopes'

const getRenderableKeyCreationScopes = (): Set<string> =>
    new Set(
        API_SCOPES.flatMap(({ key, disabledActions }) =>
            (['read', 'write'] as const)
                .filter((action) => !disabledActions?.includes(action))
                .map((action) => `${key}:${action}`)
        )
    )

describe('getScopeDescription', () => {
    it('returns the known description for a recognised scope', () => {
        expect(getScopeDescription('user:read')).toBe('Read access to users')
    })

    it('derives a readable label for OAuth-hidden scopes absent from API_SCOPES', () => {
        expect(getScopeDescription('wizard_session:write')).toBe('Write access to wizard session')
    })

    it('returns undefined for introspection so list call sites can filter it out', () => {
        expect(getScopeDescription('introspection')).toBeUndefined()
    })

    it('returns the bare scope string when there is no colon separator', () => {
        expect(getScopeDescription('baretoken')).toBe('baretoken')
    })
})

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

        it('contains :read for every entry in API_SCOPES', () => {
            const preset = findPreset('read_only_access')
            const expected = API_SCOPES.map(({ key }) => `${key}:read`).sort()
            expect([...preset.scopes].sort()).toEqual(expected)
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
