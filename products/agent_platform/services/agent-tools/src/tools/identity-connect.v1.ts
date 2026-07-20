/**
 * Mint a connect / reconnect link for an identity provider on demand. The agent
 * calls this whenever the user wants to authorize (or re-authorize) an account —
 * "connect PostHog", "relink my GitHub", or after a capability reports it needs
 * a connection. Returns a fresh authorize URL for the agent to relay as a
 * markdown link; works whether or not the user is already linked (reconnect
 * refreshes access after a revoked token or a newly-required scope).
 *
 * This is the proactive twin of the failure-driven `auth_required` / "Connect
 * required" surfacing: the agent no longer has to wait for a tool or MCP to
 * fail before it can hand the user a link.
 */

import { defineNativeTool, Type } from '@posthog/agent-shared'

export const identityConnectV1 = defineNativeTool({
    id: '@posthog/identity-connect',
    approval: 'approve',
    description:
        'Generate a connect or reconnect link for an identity provider so the user can authorize ' +
        '(or re-authorize) their account. Call this whenever the user asks to connect, reconnect, ' +
        'or relink a provider, or when a capability needs an account that is not connected yet. ' +
        'Relay the returned `authorize_url` to the user as a markdown link with a short friendly label. ' +
        'Works whether or not they are already connected — reconnecting refreshes access (e.g. after a ' +
        'revoked token or an added permission). `provider` is an id from spec.identity_providers (e.g. "posthog").',
    args: Type.Object({
        provider: Type.String({ description: 'Provider id from spec.identity_providers (e.g. "posthog", "github").' }),
    }),
    returns: Type.Object({
        authorize_url: Type.Optional(Type.String({ description: 'Relay this to the user as a markdown link.' })),
        unavailable: Type.Optional(
            Type.Object({
                provider: Type.String(),
                reason: Type.String({ description: 'Why no link could be minted (tell the user plainly).' }),
            })
        ),
    }),
    requires: {},
    cost_hint: 'cheap',
    async run(args, ctx) {
        if (!ctx.identity) {
            return {
                unavailable: { provider: args.provider, reason: 'no identity providers configured on this agent' },
            }
        }
        // `relink` force-initiates a fresh link regardless of current state — the
        // single primitive for both first-time connect and reconnect.
        const url = ctx.identity.relink ? await ctx.identity.relink(args.provider) : null
        if (url) {
            return { authorize_url: url }
        }
        // No link possible (unknown provider, shared session, unlinkable
        // principal, or a provider with no OAuth app). Resolve once for a reason.
        const res = await ctx.identity.resolve(args.provider)
        const reason = res.kind === 'unavailable' ? res.reason : 'linking is not supported for this provider'
        return { unavailable: { provider: args.provider, reason } }
    },
})
