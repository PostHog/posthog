---
description: How the agent acts on a service AS the user — the identity system. The two provider kinds (managed `posthog` vs bring-your-own `oauth2` like GitHub), the resolve outcomes (ok / link_required / unavailable), and how to hand the user a connect link via `@posthog/identity-connect` instead of failing. Load when a tool or MCP needs auth, the user mentions connecting/linking/OAuth, or a call comes back link_required.
---

# Acting as you

When you call PostHog or GitHub, you don't act as some shared service
robot — you act **as the asking user**, with _their_ token and _their_
permissions. That's the identity system. Understanding it turns a
dead-end ("I can't access that") into a one-click fix ("link your
account and I'm in").

## Two axes

1. **Principal** — _who's asking._ The person who drove this session.
2. **Credential provider** — _how you get their token._ Declared in
   `spec.identity_providers[]`. You have two:

   | Provider  | Kind                      | Used by                                | What linking looks like                                         |
   | --------- | ------------------------- | -------------------------------------- | --------------------------------------------------------------- |
   | `posthog` | managed                   | `@posthog/query`, the `posthog__*` MCP | PostHog's own consent screen — fast, they're already logged in. |
   | `github`  | `oauth2` (bring-your-own) | the `github__*` MCP                    | A GitHub OAuth consent screen.                                  |

   The `posthog` provider is provisioned automatically on promote. The
   `github` one is a real OAuth app (needs `GITHUB_OAUTH_CLIENT_SECRET`
   set) — bring-your-own, demonstrating the generic `oauth2` path any
   third party plugs into.

## The three resolve outcomes

When a tool that needs a provider runs, the platform resolves the user's
credential and you get one of:

- **`ok`** — they're linked; the call proceeds with their token. Nothing
  to do.
- **`link_required`** — they haven't linked this provider yet. **This is
  not an error.** The outcome carries an `authorizeUrl`. Hand it over.
- **`unavailable`** — the provider is misconfigured (e.g. the GitHub
  OAuth secret isn't set). This _is_ something a human must fix; say so
  plainly and, in console, offer `set_secret`.

## The connect flow

On `link_required`, use **`@posthog/identity-connect`** to produce a
clean connect link for the right provider, and say something like:

> I act on GitHub as you, and you haven't linked it yet. One-time
> connect here → {authorizeUrl}. Approve it and I'll pick up right where
> I left off.

Then end your turn. After they link, the next message resumes and the
call goes through. Use `@posthog/identity-fetch` if you need to check
what's already linked before deciding.

## Choosing scopes (for the curious)

The providers request only what the agent needs: `posthog` asks for
read scopes plus `feature_flag:write` (because two gated MCP tools
create/update flags); `github` asks `read:user`, `repo`, `read:org`.
Least-privilege is the rule — don't ask for write scopes you never use.

## The golden rule

A missing credential is a **link**, not a wall. Never tell the user "I
can't do that" when the real situation is "you haven't connected yet."
Connect-link first; only escalate to "a human needs to fix config" on
`unavailable`.
