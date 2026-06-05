import { API_KEY_SCOPE_PRESETS, API_SCOPES, HIDDEN_API_SCOPE_OBJECTS } from 'lib/scopes'

import type { APIScopeObject } from '~/types'

describe('scopes', () => {
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

        it('contains no hidden scopes in any preset', () => {
            const hidden = API_KEY_SCOPE_PRESETS.flatMap((preset) =>
                preset.scopes.filter((scope) =>
                    HIDDEN_API_SCOPE_OBJECTS.includes(scope.split(':')[0] as APIScopeObject)
                )
            )
            expect(hidden).toEqual([])
        })
    })

    describe('API_SCOPES', () => {
        it('does not offer hidden scope objects in the picker descriptor', () => {
            const offered = API_SCOPES.filter(({ key }) => HIDDEN_API_SCOPE_OBJECTS.includes(key))
            expect(offered).toEqual([])
        })
    })
})
