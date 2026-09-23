# Canvas delivery and CDN setup

## API responses

`GET /api/projects/{project_id}/canvases/{canvas_id}/view/` returns the canvas record, its published build and signed artifact URL, and its active-build state.
Before a renderable build exists, it also returns the head source.
For grids, it returns the layout and the visible components' renderable builds.
Component expansion uses the same access rules as direct canvas reads, including task-sandbox restrictions.

`GET .../layout/?include_components=true` adds component build details to the layout response.
`GET .../builds/?scope=slim` limits the build list to the published build, head-version builds, and active builds within the existing response window.
A requested historical version can still add its retained build.

These endpoints return `Cache-Control: private, no-cache` and a content-based ETag.
Send the ETag in `If-None-Match` to receive a bodyless `304` when the response has not changed.
Permission checks and response construction still run before revalidation.
Component publication, visibility changes, and renewed signed URLs change the validator.
A view response that lacks source or layout because storage failed uses `private, no-store` and has no ETag.

Keep all `/api/` responses outside the CDN cache.
The combined endpoint reduces request count only when the client uses it.

## Artifact origin

Built HTML and JavaScript are untrusted user content.
Serve them from a dedicated HTTPS origin, never the PostHog application origin or a host that receives its session cookies.
Use a separate registrable domain if application cookies cover subdomains.

`CANVAS_ARTIFACT_ORIGIN` must be a bare HTTPS origin, without a path, query, or credentials.
Every process that creates artifact URLs must use the same origin and compatible signing keys as the artifact-serving process.
Keep the existing `CANVAS_ARTIFACT_SIGNING_KEYS` configuration, or the existing `SECRET_KEY` fallback.
Do not rotate keys as part of CDN setup.

The CDN must forward requests to the existing Django artifact handler.
Do not point it directly at the object-storage bucket: that bypasses token, build, deletion, and manifest checks.
The handler accepts only the Host configured in `CANVAS_ARTIFACT_ORIGIN`.
Forward that Host through the CDN and ingress, with matching TLS and host allowlists.
The backend connection can use a separate origin hostname, but the HTTP Host must still match the artifact origin.

## Cache policy

Shared caching is off by default:

```text
CANVAS_ARTIFACT_SHARED_CACHE_SECONDS=0
```

With a positive value, successful artifact responses include `public` and a bounded `s-maxage`.
The shared-cache lifetime cannot exceed the signed token's remaining lifetime.
`must-revalidate` prevents a compliant cache from serving stale content after that lifetime.
The existing browser policy remains `max-age=31536000, immutable`.

Configure the CDN as follows:

1. Cache only successful `GET` and `HEAD` responses under `/canvas-artifacts/`.
2. Keep the complete host and path in the cache key, including the signed token and asset path. Do not remove or normalize the token. Preserve query strings unless an explicit rule rejects them.
3. Honor the origin's `Cache-Control`, including `private`, `s-maxage`, and `must-revalidate`. Set the minimum cache TTL to zero. Do not impose a fixed edge TTL that overrides the response.
4. Disable stale-on-error, stale-while-revalidate, offline copies, and negative caching for this route. Do not cache `403`, `404`, or `5xx` responses.
5. Do not forward application cookies or session authorization. The signed token in the path is the credential. Do not add `Set-Cookie` to artifact responses.
6. Preserve `Content-Type`, `Content-Encoding`, `Content-Disposition`, `ETag`, `Cache-Control`, `Content-Security-Policy`, `Access-Control-Allow-Origin`, `Cross-Origin-Resource-Policy`, `Referrer-Policy`, `X-Content-Type-Options`, and `Permissions-Policy`, including on `304` responses. Do not add `X-Frame-Options: DENY` or `SAMEORIGIN`.
7. Disable HTML and JavaScript rewriting. Redact signed-token paths from access logs, analytics, and support attachments.

For CloudFront, use a custom cache policy with minimum TTL zero, forward the artifact Host, and set error-cache TTLs to zero.
For Cloudflare, enable caching only for the artifact route, enable Origin Cache Control, and do not override the edge TTL or enable Always Online for that route.
Check the provider's behavior with an expired token before enabling shared caching.

## Rollout and verification

1. Deploy the backend with shared caching set to zero. Confirm that direct artifact delivery still works.
2. Configure the CDN, certificate, origin route, and DNS with caching disabled. Prefer retaining the existing public artifact hostname to avoid changing issued URLs and host allowlists.
3. Add the cache setting to the deployment configuration of artifact-serving web processes. It is a non-secret integer. If deployment uses a secret reference, create the referenced value before deploying that reference.
4. Enable a short shared TTL, such as `300`, in one environment or region first. Processes that only sign URLs do not need a positive shared TTL.
5. Request the same signed URL twice and confirm a cache miss followed by a hit. Check the provider cache-status header and `Age`, without publishing the token.
6. Confirm that a token changed by one character, an expired token, an unknown asset, and the wrong Host do not return cached content. Test expiry both on a warm cache and after a cache miss.
7. Open a freeform canvas and a grid. Confirm that module scripts load and that `ph.query`, `ph.state`, and declared connectors still work through the existing host bridge. Check the console for CORS and CSP failures.
8. Publish a component, then remove access to it. Confirm that a conditional grid-view request returns a new `200` response and omits inaccessible components.
9. Check artifact latency, cache hit ratio, origin errors, and canvas-open failures. Roll out further only after these checks pass.

A cache hit does not recheck database state.
Deleting a canvas, revoking a signing key, or removing a build can take up to the configured shared TTL to stop new edge responses.
Previously downloaded content cannot be revoked, and the existing browser cache may still hold it.
Keep shared caching disabled if this delay is not acceptable.
Live query, state, action, and connector calls remain authenticated API requests; the CDN must not cache them.

To roll back, set the shared TTL to zero, disable the CDN cache rule, and purge existing artifact cache entries.
Changing the environment variable alone does not remove objects that the edge already cached.
