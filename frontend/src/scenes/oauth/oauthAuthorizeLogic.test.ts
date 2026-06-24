import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { oauthAuthorizeLogic } from './oauthAuthorizeLogic'

describe('oauthAuthorizeLogic', () => {
    let logic: ReturnType<typeof oauthAuthorizeLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/users/@me/': MOCK_DEFAULT_USER,
            },
        })
        initKeaTests()
        userLogic.mount()
        logic = oauthAuthorizeLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    const effectiveScopesCases: { name: string; scopes: string[]; apply?: () => void; expected: string[] }[] = [
        {
            name: 'grants the full requested set, collapsed to the highest action',
            scopes: ['openid', 'feature_flag:read', 'feature_flag:write', 'insight:read'],
            expected: ['openid', 'feature_flag:write', 'insight:read'],
        },
        {
            name: 'downgrades every write scope to read in read-only mode',
            scopes: ['openid', 'feature_flag:write', 'dashboard:write', 'query:read'],
            apply: () => logic.actions.setReadOnlyMode(true),
            expected: ['openid', 'feature_flag:read', 'dashboard:read', 'query:read'],
        },
        {
            name: 'drops a denied object and keeps identity scopes',
            scopes: ['openid', 'email', 'feature_flag:write'],
            apply: () => logic.actions.toggleDeniedScope('feature_flag'),
            expected: ['openid', 'email'],
        },
        {
            name: 'grants the wildcard unchanged when read-only is off',
            scopes: ['openid', '*'],
            expected: ['openid', '*'],
        },
    ]

    it.each(effectiveScopesCases)('effectiveScopes $name', ({ scopes, apply, expected }) => {
        logic.actions.setScopes(scopes)
        apply?.()
        expect(logic.values.effectiveScopes).toEqual(expected)
    })

    it('offers the read-only toggle for wildcard requests', () => {
        logic.actions.setScopes(['*'])
        expect(logic.values.showReadOnlyToggle).toBe(true)
    })

    it('expands the wildcard to read scopes in read-only mode', () => {
        logic.actions.setScopes(['openid', '*'])
        logic.actions.setReadOnlyMode(true)
        const scopes = logic.values.effectiveScopes
        expect(scopes).toContain('openid')
        expect(scopes).toContain('feature_flag:read')
        expect(scopes).not.toContain('*')
        expect(scopes.some((scope) => scope.endsWith(':write'))).toBe(false)
        // Privileged/hidden objects are never grantable via /authorize; including them
        // would make the server reject the whole submit.
        expect(scopes).not.toContain('llm_gateway:read')
        expect(scopes).not.toContain('metrics:read')
    })

    it('uses the server-computed read set when expanding the wildcard', () => {
        logic.actions.setScopes(['openid', '*'])
        logic.actions.loadOAuthApplicationSuccess({
            name: 'Test App',
            client_id: 'test-client',
            is_verified: true,
            logo_uri: null,
            wildcard_read_scopes: ['insight:read', 'batch_import:read'],
        })
        logic.actions.setReadOnlyMode(true)
        expect(logic.values.effectiveScopes).toEqual(['openid', 'insight:read', 'batch_import:read'])
    })

    it('drops a scope when its object is denied and re-adds it when toggled back', () => {
        logic.actions.setScopes(['openid', 'feature_flag:write', 'insight:read'])
        logic.actions.toggleDeniedScope('feature_flag')
        expect(logic.values.effectiveScopes).toEqual(['openid', 'insight:read'])
        logic.actions.toggleDeniedScope('feature_flag')
        expect(logic.values.effectiveScopes).toEqual(['openid', 'feature_flag:write', 'insight:read'])
    })

    const withRequiredScopes = (required_scopes: string[]): void => {
        logic.actions.loadOAuthApplicationSuccess({
            name: 'Test App',
            client_id: 'test-client',
            is_verified: true,
            logo_uri: null,
            required_scopes,
        })
    }

    it('ignores denial of a required object and marks its row required', () => {
        logic.actions.setScopes(['openid', 'feature_flag:write', 'insight:read'])
        withRequiredScopes(['feature_flag:write'])
        logic.actions.toggleDeniedScope('feature_flag')
        expect(logic.values.effectiveScopes).toEqual(['openid', 'feature_flag:write', 'insight:read'])
        const row = logic.values.scopeRows.find((r) => r.key === 'feature_flag')
        expect(row).toMatchObject({ required: true, granted: true })
    })

    it('keeps a required write scope at write level in read-only mode', () => {
        logic.actions.setScopes(['openid', 'feature_flag:write', 'dashboard:write'])
        withRequiredScopes(['feature_flag:write'])
        logic.actions.setReadOnlyMode(true)
        expect(logic.values.effectiveScopes).toEqual(['openid', 'feature_flag:write', 'dashboard:read'])
    })

    it('downgrades to read in read-only mode when only the read level is required', () => {
        logic.actions.setScopes(['openid', 'feature_flag:write'])
        withRequiredScopes(['feature_flag:read'])
        logic.actions.setReadOnlyMode(true)
        expect(logic.values.effectiveScopes).toEqual(['openid', 'feature_flag:read'])
        const row = logic.values.scopeRows.find((r) => r.key === 'feature_flag')
        expect(row).toMatchObject({ required: true, granted: true })
    })

    it('marks all scopes required when every requested scope is required', () => {
        logic.actions.setScopes(['experiment:read', 'dashboard:write'])
        withRequiredScopes(['experiment:read', 'dashboard:write'])
        expect(logic.values.allScopesRequired).toBe(true)
        expect(logic.values.showReadOnlyToggle).toBe(false)
    })

    it('does not mark all required when a requested scope is declinable', () => {
        logic.actions.setScopes(['experiment:read', 'dashboard:write'])
        withRequiredScopes(['experiment:read'])
        expect(logic.values.allScopesRequired).toBe(false)
    })

    it('renders a locked row for required scopes the client did not request and grants them', () => {
        logic.actions.setScopes(['openid', 'insight:read'])
        withRequiredScopes(['feature_flag:read'])
        const row = logic.values.scopeRows.find((r) => r.key === 'feature_flag')
        expect(row).toMatchObject({ required: true, granted: true })
        expect(logic.values.effectiveScopes).toEqual(
            expect.arrayContaining(['openid', 'insight:read', 'feature_flag:read'])
        )
        expect(logic.values.effectiveScopes).toHaveLength(3)
    })

    it('lets the user decline an optional write above a required read floor', () => {
        logic.actions.setScopes(['openid', 'feature_flag:write'])
        withRequiredScopes(['feature_flag:read'])
        const floor = logic.values.scopeRows.find((r) => r.key === 'feature_flag')
        const upgrade = logic.values.scopeRows.find((r) => r.key === 'feature_flag:optional-write')
        expect(floor).toMatchObject({ required: true, granted: true, toggleKey: null })
        expect(upgrade).toMatchObject({ required: false, granted: true, toggleKey: 'feature_flag' })
        expect(logic.values.effectiveScopes).toContain('feature_flag:write')

        logic.actions.toggleDeniedScope('feature_flag')
        expect(logic.values.effectiveScopes).toEqual(['openid', 'feature_flag:read'])
        expect(logic.values.scopeRows.find((r) => r.key === 'feature_flag:optional-write')).toMatchObject({
            granted: false,
        })

        logic.actions.toggleDeniedScope('feature_flag')
        expect(logic.values.effectiveScopes).toContain('feature_flag:write')
    })

    it('renders the write level when a required write upgrades a requested read', () => {
        logic.actions.setScopes(['openid', 'feature_flag:read'])
        withRequiredScopes(['feature_flag:write'])
        const row = logic.values.scopeRows.find((r) => r.key === 'feature_flag')
        expect(row).toMatchObject({ required: true, granted: true })
        expect(row?.description).toContain('Write')
        expect(logic.values.effectiveScopes).toContain('feature_flag:write')
        expect(logic.values.effectiveScopes).not.toContain('feature_flag:read')
    })

    it('resets read-only mode and denied scopes when scopes are reloaded', () => {
        logic.actions.setScopes(['openid', 'feature_flag:write'])
        logic.actions.setReadOnlyMode(true)
        logic.actions.toggleDeniedScope('feature_flag')
        logic.actions.setScopes(['openid', 'insight:write'])
        expect(logic.values.readOnlyMode).toBe(false)
        expect(logic.values.deniedScopeObjects).toEqual([])
        expect(logic.values.effectiveScopes).toEqual(['openid', 'insight:write'])
    })
})
