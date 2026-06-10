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
        expect(logic.values.hasWriteScopes).toBe(true)
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

    it('drops a scope when its object is denied and re-adds it when toggled back', () => {
        logic.actions.setScopes(['openid', 'feature_flag:write', 'insight:read'])
        logic.actions.toggleDeniedScope('feature_flag')
        expect(logic.values.effectiveScopes).toEqual(['openid', 'insight:read'])
        logic.actions.toggleDeniedScope('feature_flag')
        expect(logic.values.effectiveScopes).toEqual(['openid', 'feature_flag:write', 'insight:read'])
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
