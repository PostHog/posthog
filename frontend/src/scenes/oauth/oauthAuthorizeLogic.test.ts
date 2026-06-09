import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

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

    it('grants the full requested set (collapsed to highest action) by default', async () => {
        await expectLogic(logic, () => {
            logic.actions.setScopes(['openid', 'feature_flag:read', 'feature_flag:write', 'insight:read'])
        }).toMatchValues({
            effectiveScopes: ['openid', 'feature_flag:write', 'insight:read'],
        })
    })

    it('downgrades write scopes to read in read-only mode', async () => {
        logic.actions.setScopes(['openid', 'feature_flag:write', 'dashboard:write', 'query:read'])
        await expectLogic(logic, () => {
            logic.actions.setReadOnlyMode(true)
        }).toMatchValues({
            effectiveScopes: ['openid', 'feature_flag:read', 'dashboard:read', 'query:read'],
        })
    })

    it('drops a scope when its object is denied, and re-adds it when toggled back', async () => {
        logic.actions.setScopes(['openid', 'feature_flag:write', 'insight:read'])
        await expectLogic(logic, () => {
            logic.actions.toggleDeniedScope('feature_flag')
        }).toMatchValues({
            effectiveScopes: ['openid', 'insight:read'],
        })
        await expectLogic(logic, () => {
            logic.actions.toggleDeniedScope('feature_flag')
        }).toMatchValues({
            effectiveScopes: ['openid', 'feature_flag:write', 'insight:read'],
        })
    })

    it('keeps identity scopes even when every resource scope is denied', async () => {
        logic.actions.setScopes(['openid', 'email', 'feature_flag:write'])
        await expectLogic(logic, () => {
            logic.actions.toggleDeniedScope('feature_flag')
        }).toMatchValues({
            effectiveScopes: ['openid', 'email'],
        })
    })

    it('resets read-only mode and denied scopes when scopes are reloaded', async () => {
        logic.actions.setScopes(['openid', 'feature_flag:write'])
        logic.actions.setReadOnlyMode(true)
        logic.actions.toggleDeniedScope('feature_flag')
        await expectLogic(logic, () => {
            logic.actions.setScopes(['openid', 'insight:write'])
        }).toMatchValues({
            readOnlyMode: false,
            deniedScopeObjects: [],
            effectiveScopes: ['openid', 'insight:write'],
        })
    })
})
