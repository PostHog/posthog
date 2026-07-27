import { describe, expect, it } from 'vitest'

import { deriveIdentityProviders } from './server'

const SLACK = { type: 'slack', config: { trusted_workspaces: '*' } }
const QUERY = { kind: 'native', id: '@posthog/query' } // requires posthog scope query:read

describe('deriveIdentityProviders (freeze auto-wire)', () => {
    it('adds a posthog provider with the union of native-tool scopes for a Slack agent', () => {
        const out = deriveIdentityProviders({ triggers: [SLACK] }, [QUERY])
        expect(out).toEqual([{ kind: 'posthog', id: 'posthog', scopes: ['query:read'] }])
    })

    it('does NOT add a provider for a chat/MCP agent (passthrough seed covers it)', () => {
        expect(deriveIdentityProviders({ triggers: [{ type: 'chat', config: {} }] }, [QUERY])).toEqual([])
    })

    it('scope-unions onto an author-declared posthog provider', () => {
        const out = deriveIdentityProviders(
            { triggers: [SLACK], identity_providers: [{ kind: 'posthog', id: 'posthog', scopes: ['extra'] }] },
            [QUERY]
        )
        expect(out).toEqual([{ kind: 'posthog', id: 'posthog', scopes: ['extra', 'query:read'] }])
    })

    it('leaves declared providers untouched when no native posthog tool is present', () => {
        const declared = [{ kind: 'oauth2', id: 'github' }]
        expect(deriveIdentityProviders({ triggers: [SLACK], identity_providers: declared }, [])).toEqual(declared)
    })
})
