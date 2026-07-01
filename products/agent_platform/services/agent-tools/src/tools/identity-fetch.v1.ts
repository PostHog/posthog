/**
 * Call a linked identity provider's API as the current asker. Resolves their
 * per-principal OAuth credential via `ctx.identity`; if unlinked, returns an
 * `auth_required` link for the agent to relay. The target host must belong to
 * the provider (the resolver's allowedHosts) so a user's bearer can't be aimed
 * at an arbitrary URL.
 */

import { defineNativeTool, Type } from '@posthog/agent-shared'

export const identityFetchV1 = defineNativeTool({
    id: '@posthog/identity-fetch',
    approval: 'allow',
    description:
        "Call a linked identity provider's API as the current user. If the user hasn't " +
        'linked that provider yet, returns an `auth_required` link to send them. The URL ' +
        'host must belong to the provider (from spec.identity_providers).',
    args: Type.Object({
        provider: Type.String({ description: 'Provider id from spec.identity_providers (e.g. "github").' }),
        url: Type.String({ description: "Absolute URL on the provider's API host." }),
        method: Type.Optional(Type.String({ description: 'HTTP method. Default GET.' })),
    }),
    returns: Type.Object({
        auth_required: Type.Optional(Type.Object({ provider: Type.String(), authorize_url: Type.String() })),
        status: Type.Optional(Type.Number()),
        body: Type.Optional(Type.Unknown()),
    }),
    requires: {},
    cost_hint: 'medium',
    async run(args, ctx) {
        if (!ctx.identity) {
            throw new Error('identity_unavailable: no identity providers configured on this agent')
        }
        const res = await ctx.identity.resolve(args.provider)
        if (res.kind === 'link_required') {
            return { auth_required: { provider: res.provider, authorize_url: res.authorizeUrl } }
        }
        if (res.kind === 'unavailable') {
            throw new Error(`identity_unavailable: ${args.provider} (${res.reason})`)
        }
        const host = new URL(args.url).host
        if (!res.allowedHosts.includes(host)) {
            throw new Error(`identity_host_not_allowed: ${host} not a ${args.provider} host`)
        }
        const token =
            res.credential.kind === 'oauth_bearer' || res.credential.kind === 'posthog_bearer'
                ? res.credential.token
                : undefined
        if (!token) {
            throw new Error('identity_credential_not_bearer')
        }
        const resp = await ctx.http.fetch(args.url, {
            method: args.method ?? 'GET',
            headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
        })
        let body: unknown
        try {
            body = await resp.json()
        } catch {
            body = await resp.text().catch(() => null)
        }
        return { status: resp.status, body }
    },
})
