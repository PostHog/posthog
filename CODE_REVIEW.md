# Code Review: PR #48838 — `feat: add oauth.posthog.com cross-region OAuth proxy`

**Reviewer**: Claude Code Review Agent
**PR**: https://github.com/PostHog/posthog/pull/48838
**Author**: MattBro
**Date**: 2026-02-26

## Summary

This PR adds a new Cloudflare Worker service (`services/oauth-proxy/`) that serves as a single OAuth endpoint (`oauth.posthog.com`) to proxy OAuth flows across PostHog's US and EU regions. The proxy eliminates the requirement for MCP clients to know their region before initiating OAuth.

**Scope**: ~1,100 lines added across 26 files (new service, CI workflow, tests).

---

## Verdict: Approve with suggestions

The overall architecture is sound — a lightweight Cloudflare Worker with KV-backed state is the right approach for this problem. The code is well-organized, tests cover the critical paths, and security headers are present on the region picker page. The issues below are improvements rather than blockers.

---

## Issues Found

### 1. Security: Client secrets stored in KV without encryption

**Severity**: High
**File**: `services/oauth-proxy/src/handlers/register.ts:76-81`

```typescript
if (usData.client_secret) {
    mapping.us_client_secret = usData.client_secret as string
}
if (euData.client_secret) {
    mapping.eu_client_secret = euData.client_secret as string
}
```

Client secrets are stored as plaintext JSON in Cloudflare KV. While KV is not publicly accessible, this is a defense-in-depth concern — if the KV namespace is ever exposed (misconfiguration, leaked API token), all client secrets are immediately compromised.

**Suggestions**:
- Encrypt secrets at rest using a Worker secret (e.g., AES-GCM with a key from `env`)
- Or, avoid storing secrets entirely — the proxy may not need them if the regional servers handle confidential client auth directly
- At minimum, document the security implications and ensure the KV namespace has restricted access

### 2. Security: Region selection stored by `client_id` is racy for concurrent users

**Severity**: High
**File**: `services/oauth-proxy/src/handlers/authorize.ts:54-56`

```typescript
if (clientId) {
    kvWrites.push(putRegionSelection(kv, clientId, region))
}
```

Region selection is stored keyed by `client_id`. If two users of the same MCP client authorize concurrently and pick different regions, they'll overwrite each other's selection. The token exchange then routes the second user's auth code to the wrong region.

The `state` parameter key is correct (unique per flow), but the token endpoint (`token.ts:31-35`) looks up region by `client_id`, not `state`:

```typescript
if (clientId) {
    const region = await getRegionSelection(kv, clientId)
    // ...
}
```

**Suggestion**: Use a per-flow key for region routing during token exchange. The OAuth `state` parameter is the natural choice, but it isn't sent to the token endpoint. Consider:
- Using the authorization `code` as the KV key instead (unique per flow, available at token exchange)
- Or, encoding the region in the `redirect_uri` or a custom parameter that round-trips through the regional server

### 3. Logic: `handleIntrospect` doesn't use KV region routing

**Severity**: Medium
**File**: `services/oauth-proxy/src/handlers/passthrough.ts:31-63`

The introspect handler always tries US first, then EU, even though the region may be known from KV. This adds unnecessary latency for EU tokens. Other handlers (revoke, token) use `routeByClientId` to check KV first.

**Suggestion**: Extract the `client_id` from the introspect request body and check KV for a stored region before falling back to try-both.

### 4. Logic: `tryBothRegions` is sequential, not parallel

**Severity**: Medium
**File**: `services/oauth-proxy/src/lib/proxy.ts:67-103`

```typescript
const usResponse = await fetch(usUrl.toString(), { ... })
if (usResponse.ok) {
    return { response: usResponse, region: 'us' }
}
// ... then try EU
```

The try-both fallback always tries US first, then EU sequentially. For EU users whose region isn't stored, this adds the full US round-trip latency before the EU attempt.

**Suggestion**: Consider firing both requests in parallel and returning the first success. This is a tradeoff (doubles outbound requests) but significantly improves worst-case latency. At minimum, document that US is always tried first and why.

### 5. Logic: `toRegion` function is exported but never used

**Severity**: Low
**File**: `services/oauth-proxy/src/lib/constants.ts:12-14`

```typescript
export function toRegion(value: string | undefined | null): Region {
    return value?.toLowerCase() === 'eu' ? 'eu' : 'us'
}
```

This utility is defined but never imported anywhere in the codebase. Dead code.

**Suggestion**: Remove it, or use it in `authorize.ts` where the region is currently validated with a manual check (`selectedRegion === 'us' || selectedRegion === 'eu'`).

### 6. Robustness: No error handling for `JSON.parse` in body parsing

**Severity**: Medium
**File**: `services/oauth-proxy/src/handlers/passthrough.ts:88`, `token.ts:14`

```typescript
const json = JSON.parse(body) as Record<string, unknown>
```

If a client sends a malformed JSON body with `Content-Type: application/json`, this will throw an unhandled exception. The top-level catch in `index.ts` will return a 500, but the error message won't be helpful.

**Suggestion**: Wrap JSON parsing in a try-catch and return a proper OAuth error (`invalid_request`) with a descriptive message.

### 7. Config: KV namespace ID is a placeholder

**Severity**: Medium
**File**: `services/oauth-proxy/wrangler.jsonc:29`

```json
"id": "TODO_REPLACE_WITH_KV_NAMESPACE_ID"
```

This will fail on deploy. While the PR description acknowledges this, a deploy would succeed the CI checks but fail at runtime.

**Suggestion**: Add a CI step or pre-deploy check that validates the KV namespace ID is not a TODO placeholder, or use `wrangler.toml` environments to separate dev/prod configs.

### 8. Hardcoded scopes list will drift from regional servers

**Severity**: Medium
**File**: `services/oauth-proxy/src/handlers/metadata.ts:13-42`

The `scopes_supported` list is hardcoded in the proxy. When scopes are added/removed on regional servers, this list must be manually kept in sync.

**Suggestion**: Consider fetching the scopes from one of the regional servers' `/.well-known/oauth-authorization-server` at startup or with a cache, rather than hardcoding. Alternatively, add a comment noting this must be kept in sync and reference where the source of truth lives.

### 9. Minor: `handleUserInfo` always uses POST via `tryBothRegions`

**Severity**: Low
**File**: `services/oauth-proxy/src/handlers/passthrough.ts:69-72`

```typescript
export async function handleUserInfo(request: Request): Promise<Response> {
    const { response } = await tryBothRegions(request, '/oauth/userinfo/')
    return response
}
```

The userinfo endpoint is typically a GET request (RFC 7662), but `tryBothRegions` hardcodes `method: 'POST'`. If a client sends a GET, the proxy will forward it as POST, which may fail.

**Suggestion**: Make `tryBothRegions` respect the original request method, or add a separate `tryBothRegionsGet` variant.

### 10. Minor: `handleJwks` assumes US and EU keys are identical

**Severity**: Low
**File**: `services/oauth-proxy/src/handlers/passthrough.ts:77-79`

```typescript
export async function handleJwks(request: Request): Promise<Response> {
    return proxyToRegion(request, 'us', '/.well-known/jwks.json')
}
```

The comment says "keys should be the same across regions" but this isn't validated. If they ever diverge (key rotation timing, separate key pairs), token verification for EU tokens would fail.

**Suggestion**: Add a comment about this assumption and consider merging JWKS from both regions, or proxying to the region that issued the token.

### 11. Test: Missing test for partial registration failure

**Severity**: Low
**File**: `services/oauth-proxy/tests/register.test.ts`

Tests cover both-succeed and both-fail, but not the case where US succeeds and EU fails (or vice versa). This is an important edge case since the proxy still stores a mapping with one empty `client_id`.

**Suggestion**: Add tests for partial failure in both directions and verify the mapping handles the empty string correctly downstream.

### 12. CI: Copyright year will need updating

**Severity**: Very Low
**Files**: `services/oauth-proxy/src/static/region-picker.html:148`, `services/mcp/src/static/landing.html:388`

Both files hardcode `© 2025`. This is fine for now but will need updating.

**Suggestion**: Consider using a dynamic year or a range like `© 2024–2025`.

---

## Positive Observations

- **Clean architecture**: The handler/lib/static separation is clear and easy to follow
- **Security headers**: Region picker correctly sets `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, and `Referrer-Policy: no-referrer`
- **Smart token exchange safety**: Refusing to try-both for `authorization_code` grants prevents leaking auth codes to the wrong region
- **Good test coverage**: All major handlers have tests, including parameterized router tests
- **KV TTL on region selections**: 1-hour expiry prevents stale data accumulation
- **CI workflow**: Properly scoped with path-based filtering and a gate job pattern
