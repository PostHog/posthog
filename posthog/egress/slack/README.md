# Slack egress

## Identity

The Slack workspace id for Web API calls.
The Retry-After gauge adds the app id to its `resource` label, because Slack applies a 429 to one app and one method.

## Budget

None: Slack calls are recorded, never gated (`RecordedEgressClient`).
Slack applies Web API limits per method, workspace, and app, with special limits such as per-channel message posting.
Installation age and Marketplace status also change the limits for history methods.
With no single budget to draw from, a proactive limiter would guess, so callers keep owning reactive retries.

## Lanes and callers

No lanes, because nothing is gated.

- Slack SDK calls use `SlackWebClient` or `SlackAsyncWebClient` from `client.py` and `async_client.py`. A retry handler records every HTTP attempt, including each retry.
- `SlackIntegration(integration, source=...)` sets the `source` label on the clients it builds. A flow that posts on its own, such as an alert, a digest, or a subscription, passes its own name, so its calls and 429s are separate from other callers. A caller that passes no name records as `integration`.
- Direct HTTP calls, such as file downloads in `posthog/temporal/ai/slack_app/attachments.py`, use `slack_request`.
- OAuth code exchanges in `posthog/models/integration/oauth.py` and MCP Store token exchanges and refreshes record their responses with `record_slack_api_response`.

The `slack-api-calls-go-through-egress` semgrep rule fails CI on a bare `WebClient` or a raw `requests` call to `slack.com/api`.

Incoming webhooks and interactivity `response_url` calls are not Web API calls.
Their secret URL is the budget identity, and persisting or labeling by it would expose credentials, so their error handling stays with the caller.

## Rate-limit headers

Slack returns no remaining-budget headers.
A 429's `Retry-After` sets `slack_api_rate_limit_reset_timestamp_seconds`, labeled `workspace_id` and `resource` as `<app_id>:<method>`.
The counter is `slack_api_requests_total`, labeled `workspace_id, method, endpoint, status_code, source`.

## Auth

The caller passes its bot or user token.

## Sources

- [Web API rate limits](https://docs.slack.dev/apis/web-api/rate-limits): limits per method and workspace, the Marketplace change, and `Retry-After` on a 429.
