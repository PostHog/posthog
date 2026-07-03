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

    const HINT_TEAMS = [
        { id: 11, organization: 'org-a', name: 'A project' },
        { id: 22, organization: 'org-b', name: 'B project' },
    ]
    const CURRENT_TEAM = {
        id: MOCK_DEFAULT_USER.team?.id,
        organization: MOCK_DEFAULT_USER.organization?.id,
        name: 'Current project',
    }

    // Once teams load, a team_id hint resolves to that project + its org; an
    // inaccessible hint falls back to the user's current org/team.
    const hintResolutionCases: {
        name: string
        hint: number
        teams: any[]
        expectedOrg: string | undefined
        expectedTeams: (number | undefined)[]
    }[] = [
        {
            name: 'resolves the hinted project and its org from the team_id param',
            hint: 22,
            teams: HINT_TEAMS,
            expectedOrg: 'org-b',
            expectedTeams: [22],
        },
        {
            name: 'falls back to the current org/team when the hinted team is inaccessible',
            hint: 999,
            teams: [...HINT_TEAMS, CURRENT_TEAM],
            expectedOrg: MOCK_DEFAULT_USER.organization?.id,
            expectedTeams: [MOCK_DEFAULT_USER.team?.id],
        },
    ]

    it.each(hintResolutionCases)('team_id hint $name', ({ hint, teams, expectedOrg, expectedTeams }) => {
        logic.actions.setTeamHint(hint)
        logic.actions.setRequiredAccessLevel('team')
        logic.actions.loadAllTeamsSuccess(teams as any)
        expect(logic.values.teamHint).toBeNull()
        expect(logic.values.selectedOrganization).toBe(expectedOrg)
        expect(logic.values.oauthAuthorization.scoped_teams).toEqual(expectedTeams)
    })

    // Before teams load, a pending hint suppresses the eager current-org selection
    // (so a fast CTA click can't authorize the wrong project), while the no-hint
    // path keeps pre-selecting the current org/team.
    const eagerSelectionCases: {
        name: string
        hint: number | null
        expectedOrg: string | null | undefined
        expectedTeams: (number | undefined)[]
    }[] = [
        {
            name: 'leaves the selection empty while a team_id hint is pending',
            hint: 22,
            expectedOrg: null,
            expectedTeams: [],
        },
        {
            name: 'pre-selects the current org/team when no team_id hint is given',
            hint: null,
            expectedOrg: MOCK_DEFAULT_USER.organization?.id,
            expectedTeams: [MOCK_DEFAULT_USER.team?.id],
        },
    ]

    it.each(eagerSelectionCases)('before teams load, $name', ({ hint, expectedOrg, expectedTeams }) => {
        if (hint !== null) {
            logic.actions.setTeamHint(hint)
        }
        logic.actions.setRequiredAccessLevel('team')
        expect(logic.values.selectedOrganization).toBe(expectedOrg)
        expect(logic.values.oauthAuthorization.scoped_teams).toEqual(expectedTeams)
    })
})
