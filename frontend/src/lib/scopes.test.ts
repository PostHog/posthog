import {
    AGENT_CLI_API_KEY_SCOPES,
    API_KEY_SCOPE_PRESETS,
    API_SCOPES,
    type ScopePickerRow,
    clampScopeLevel,
    getScopeDescription,
    scopeGroupLevel,
    scopeGroupTooltip,
    scopeMatchesSearch,
    summarizeScopesByGroup,
} from 'lib/scopes'

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

describe('scope access groups', () => {
    const row = (key: string, value: ScopePickerRow['value'], disabledReasons = {}): ScopePickerRow => ({
        key,
        label: key,
        value,
        disabledReasons,
    })

    // The clamp has to go down for a level the row refuses and up for a level the app requires,
    // because the key modal only has the first case and the consent screen has both.
    it.each([
        ['stays on an allowed level', row('a', 'none'), 'write', 'write'],
        ['drops to read when write is refused', row('a', 'none', { write: 'Not requested' }), 'write', 'read'],
        [
            'drops to none when read and write are refused',
            row('a', 'none', { read: 'No', write: 'No' }),
            'write',
            'none',
        ],
        ['rises to read when none is refused', row('a', 'write', { none: 'Required' }), 'none', 'read'],
    ])('%s', (_name, model, level, expected) => {
        expect(clampScopeLevel(model, level as ScopePickerRow['value'])).toBe(expected)
    })

    it('never selects a level no row can take, and names each row reason in the tooltip', () => {
        const rows = [
            row('a', 'read', { write: 'Not requested by App' }),
            row('b', 'read', { write: 'Not available for project scoped keys' }),
            row('c', 'write'),
        ]
        expect(scopeGroupLevel(rows)).toBe('write')
        expect(scopeGroupTooltip(rows, 'write')).toBe(
            '1 of these permissions stays at read: Not requested by App. 1 of these permissions stays at read: Not available for project scoped keys.'
        )
        expect(scopeGroupLevel(rows.slice(0, 2))).toBe('read')
        expect(scopeGroupLevel([row('a', 'read'), row('b', 'none')])).toBeUndefined()
    })
})

describe('scopeMatchesSearch', () => {
    const featureFlag = { key: 'feature_flag', objectName: 'Feature flag', objectPlural: 'feature flags' }

    it('matches every scope for an empty or whitespace term', () => {
        expect(scopeMatchesSearch(featureFlag, '')).toBe(true)
        expect(scopeMatchesSearch(featureFlag, '   ')).toBe(true)
    })

    // The regression this guards: the picker shows objectName, so a search on that label must match.
    it.each([
        ['key', 'feature_flag'],
        ['objectName', 'Feature flag'],
        ['objectPlural', 'feature flags'],
        ['a single word from the label', 'flag'],
        ['tokens in any order', 'flag feature'],
    ])('matches on %s', (_field, term) => {
        expect(scopeMatchesSearch(featureFlag, term)).toBe(true)
    })

    it('matches on the info text and ignores non-string info', () => {
        expect(scopeMatchesSearch({ key: 'query', objectName: 'Query', info: 'Run SQL' }, 'sql')).toBe(true)
        expect(scopeMatchesSearch({ key: 'query', objectName: 'Query', info: undefined }, 'undefined')).toBe(false)
    })

    it('matches on label for rows that carry no objectName', () => {
        expect(scopeMatchesSearch({ key: 'cohort', label: 'Cohort' }, 'cohort')).toBe(true)
    })

    it('returns false when a token matches no field', () => {
        expect(scopeMatchesSearch(featureFlag, 'dashboard')).toBe(false)
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

        it('contains :read for every readable entry in API_SCOPES except unprivileged-excluded scopes', () => {
            const preset = findPreset('read_only_access')
            const expected = API_SCOPES.filter(
                ({ unprivilegedExcluded, disabledActions }) =>
                    !unprivilegedExcluded && !disabledActions?.includes('read')
            )
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

        it('uses the generated Agent CLI scopes with key-disabled and opt-in-only writes removed', () => {
            const preset = findPreset('agent_cli')
            expect(preset.scopes).toEqual(AGENT_CLI_API_KEY_SCOPES)
            expect(preset.scopes).toEqual(
                expect.arrayContaining(['user:read', 'project:read', 'query:read', 'insight:write'])
            )
            expect(preset.scopes).not.toContain('file_system:write')
            expect(preset.scopes).not.toContain('integration:write')
            expect(preset.scopes).not.toContain('user:write')
        })
    })

    it('leaves integration write for a person to choose instead of adding it in the MCP Server preset', () => {
        const preset = findPreset('mcp_server')
        expect(preset.scopes).toContain('integration:read')
        expect(preset.scopes).not.toContain('integration:write')
    })

    it.each(API_KEY_SCOPE_PRESETS.filter(({ value }) => value !== 'all_access').map(({ value }) => value))(
        'preset %s only sets levels the key creation UI can render',
        (value) => {
            const renderableScopes = getRenderableKeyCreationScopes()
            const unrenderable = findPreset(value).scopes.filter((scope) => !renderableScopes.has(scope))
            expect(unrenderable).toEqual([])
        }
    )
})

describe('summarizeScopesByGroup', () => {
    it('counts each object once at its highest level, grouped in picker order', () => {
        expect(
            summarizeScopesByGroup([
                'feature_flag:read',
                'feature_flag:write',
                'session_recording:read',
                'insight:write',
                'insight:read',
                'dashboard:read',
                'not_a_real_object:read',
            ])
        ).toEqual([
            { label: 'Product analytics', write: 1, read: 1 },
            { label: 'Session replay', write: 0, read: 1 },
            { label: 'Feature flags, experiments & surveys', write: 1, read: 0 },
            { label: 'Other', write: 0, read: 1 },
        ])
    })
})
