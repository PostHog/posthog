# Is the MCP `Mcp-Session-Id` header reliable?

Tested against `mcp.posthog.com` by tailing the backing Cloudflare Worker live for ~75 seconds and inspecting 1,731 captured request/response pairs.

## Verdict

**Reliable.** The header behaves the way the Streamable HTTP MCP spec describes: server-minted, server-validated, and backed by per-session server state.

## What the data showed

| Property                | Observation                                                                                                                                                                                                |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Format                  | 64-char lowercase hex (256-bit)                                                                                                                                                                            |
| Auth ordering           | Unauthenticated requests get `401` before any session is minted — auth gates session creation                                                                                                              |
| Client binding          | 547 distinct sessions observed; 0 had more than one user-agent; 6 had more than one IP, all from a single NAT pool with the same UA                                                                        |
| Server-side state       | Each `mcp-session-id` is the name of a Cloudflare Durable Object. In the capture window: 51 fresh `setInitializeRequest` (mint) vs. 452 `getInitializeRequest` (replay) — server state is keyed on the sid |
| Persistence             | Long-running clients hold one sid for 100+ consecutive requests; no mid-stream rotation observed                                                                                                           |
| Lifetime in window      | median 0s, p95 2s, max 61s — most sessions are single-shot tool calls, sustained clients are the exception                                                                                                 |
| Header inbound coverage | 1,504 of 1,731 requests (~87%) carried `mcp-session-id` on the way in; the rest were initialize POSTs, well-known discovery probes, redirects, and auth failures                                           |

## What I could not directly observe

- The `mcp-session-id` **response** header on an initialize call. Worker tail records `response.headers = {}` for streamed responses, and `POST /mcp` replies as SSE, so the response header bag is empty in the trace. Zero of 1,731 captured responses surfaced the header. This is a tail-visibility limitation, not a server flaw — all other signals (server-side DO state, client behaviour, auth ordering) are consistent with the server minting and returning the header normally.
- The worker's structured log line is `{requestId, method, pathname, mcpClientName, status, durationMs}` — **no session id in worker logs**. To trace a specific session you need the request's incoming `mcp-session-id` header captured upstream (e.g. via the event analytics pipeline).

## Reproduction

1. Cloudflare API token with `Account > Workers Scripts > Read` and `Account > Workers Tail > Read` scoped to the account hosting the Worker.
2. Create a tail:
    ```bash
    curl -s -X POST \
      "https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/workers/scripts/$SCRIPT/tails" \
      -H "Authorization: Bearer $CF_TOKEN" -d '{}'
    ```
3. Connect to the returned `wss://tail.developers.workers.dev/<id>` with the `trace-v1` WebSocket subprotocol and consume JSON frames.
4. Frames include `event.request`, `event.response`, durable-object RPC events, and structured logs. Each frame is one Worker invocation.

## Practical takeaways

- Treat `mcp-session-id` as a stable per-client handle for the life of an MCP conversation, not a per-request token.
- Don't rely on Cloudflare Worker logs alone to debug a specific session — they don't print the sid. Log it explicitly in the Worker code, or join against upstream event capture that records request headers.
- The header rides through SSE responses, so anything that strips streamed response headers (tail tooling, some proxies, some observability shims) will hide the mint event even though it happened.
