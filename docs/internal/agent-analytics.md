# Agent analytics

Agent analytics is an alpha Web analytics view at `/web/agents`. `FEATURE_FLAGS.WEB_ANALYTICS_AGENT_ANALYTICS` controls access.

The view uses events classified by PostHog's virtual bot properties. Its default scope includes AI assistants and AI search traffic. People can include AI crawlers separately.

## Views

- **Overview** reports server requests and client navigations separately, then summarizes 4xx responses, common issues, popular pages, and agent journeys.
- **Journeys** groups server requests into request sequences, shows the confidence of each grouping, and labels timeline transitions as confirmed, sequential, or simultaneous. It also reports requests following the configured `llms.txt` URL.
- **Issues** groups missing pages by either exact URL or a normalized host and path. Normalization removes common content extensions, version tokens, and trailing slashes; it preserves path case and does not infer semantic intent.
- **Readiness** reports request-header coverage and format negotiation by agent, compares observed successful server requests with links loaded from a public `llms.txt` URL, and reports observed content-format preferences. URL content is fetched on demand with SSRF protection, a redirect limit, and a 1 MB response limit. It is not stored.

Scanner paths and static assets are excluded from issue and content-demand results. A markdown request counts as repeated work only when the same client and session requested the HTML version within 30 minutes. Missing session IDs fall back to client and time matching.

Journeys prefer `$agent_session_id`, then `$session_id`. Without either property, requests from the same client, classified agent, and domain remain in one inferred journey until the client is inactive for 30 minutes. Domains remain separate even when an explicit session ID is reused. Journey timelines never claim to represent a conversation. A transition is confirmed only when the referrer points to the previous path; identical timestamps are labeled simultaneous; other transitions are sequential.

Request anatomy reads only allowlisted HTTP metadata. It classifies `Accept` using the effective quality values for `text/markdown`, `text/html`, `text/*`, and `*/*`. Missing headers remain unknown, and `q=0` media ranges are not treated as accepted. The view reports capture coverage instead of filling missing headers from an agent lookup table.

When a conversion goal is selected, conversion metrics count distinct agent clients followed by the selected action or custom event within 24 hours. Events with session IDs must share a session. Events without one fall back to client and time matching. This is ordered attribution, not a claim of causality.

## Behavior and filters

The view exposes the assumptions that are likely to vary by site:

- Agent traffic includes the `ai_assistant` and `ai_search` traffic categories. The crawler toggle also includes `ai_crawler`.
- Server request metrics and tables use `$http_log`. Client navigation metrics use `$pageview` and `$screen`. The two sources are never added together as a single request total.
- The view reuses the Web analytics date, comparison, test-account, domain, device, country, referrer, and property filters.
- The Issues view can group similar missing URLs or keep each exact URL separate.
- Content gaps are HTTP 404 responses. Normalized grouping removes common content extensions, semantic-version fragments, and trailing slashes.
- Malformed paths contain `/null` or `/undefined`.
- llms.txt discovery uses the path and host of the loaded URL. Without a loaded URL, it uses `/llms.txt` on any host.
- The next-request table uses the first different server request in the same journey within 30 minutes, so client, agent, domain, and explicit-session boundaries remain intact.
- Request anatomy reads `$http_request_accept` and `$http_response_content_type`. Status reads `$http_response_status_code` first and falls back to `proxy_status_code` during migration.
- A markdown retry requires the HTML request to occur before the markdown request for the same client, session, domain, and page within 30 minutes.
- llms.txt coverage ignores query strings and fragments. It matches the origin and case-sensitive path, treating an appended `.md` as the same page. Relative links resolve against the fetched file's final URL. The page table shows each request's domain and warns when none of the file's links match an observed domain.
- The overview requests five rows for What agents read. Long tables request 25 rows per page and reset to the first page when filters change. Coverage and share labels describe the current page. Journey timelines show at most the first 50 requests. Responses include `hasMore`, `limit`, and `offset` for pagination.

The Vercel log-drain transformation maps its available fields to `$http_request_method`, `$referrer`, `$http_response_status_code`, `$http_response_bytes`, `$http_cache_status`, and `$agent_request_id`. Vercel's native drain does not provide `Accept`, response `Content-Type`, or an agent session ID, so those fields require edge or application instrumentation. The transformation never captures arbitrary headers.

Scanner, static-asset, malformed-path, content-extension, Accept, and version-pattern classifiers remain shared product definitions. Their version is returned with every response so changes can be tracked explicitly.

## Query architecture

The frontend sends typed `WebAgentAnalyticsQuery` nodes. `WebAgentAnalyticsQueryRunner` owns the HogQL templates and inherits Web analytics filtering, access-control, caching, and query-observability behavior.

The available query modes are overview, issues, page requests, transitions, demand, issue variants, request anatomy, journey summary, journeys, and journey detail. `intentKey` and `journeyKey` are accepted only as value placeholders for detail lookups; the frontend cannot submit HogQL.
