# OpenAI Live session creation

This domain creates WebRTC sessions for the staff voice pilot.
The OpenAI API key identifies the account budget and is hashed before use in limiter keys or metrics.
Audio travels directly between the client and OpenAI.

The per-minute and hourly limits are operator ceilings on session creation, not vendor rate limits or limits on call duration.
They use `OPENAI_LIVE_EGRESS_PER_MINUTE_BUDGET` and `OPENAI_LIVE_EGRESS_HOURLY_BUDGET`.
Interactive requests use the NORMAL lane with the default priority reserves.
No provider rate-limit header gauges are declared.
The transport does not retry session creation because each request can create a billable session.
Failure logs include the exception class and HTTP status when available, without provider response bodies, SDP, or credentials.

## Configuration

Set `OPENAI_LIVE_API_KEY` on the Django server to a key with access to `gpt-live-1`.
Clients that request `structured_tools: true` also need access to `gpt-5.6-luna` for Responses delegation.
The delegated model exposes only `send_to_task` and `answer_question`; Desktop validates the current question and executes calls through existing task controls.
Clients that omit this field retain client delegation.
Configure `OPENAI_LIVE_API_KEY` through the deployment secret store and chart before enabling `posthog-desktop-voice`.
Set the optional session-creation budgets through `OPENAI_LIVE_EGRESS_PER_MINUTE_BUDGET` and `OPENAI_LIVE_EGRESS_HOURLY_BUDGET` if the defaults do not fit the deployment.
Keep the flag off until the Desktop build and backend configuration are available.
The endpoint also requires a staff user, task access, and organization AI consent.
Sandbox tokens cannot create sessions.
The request sets `store: false` to disable session recording and forking.
The client sends `session.close` after five minutes; this is not a server-enforced spend cap.

## Sources

- https://developers.openai.com/api/docs/guides/voice-webrtc documents the session creation request and initialization charge.
- https://developers.openai.com/api/docs/guides/live documents duration billing and separate backend usage.

- https://developers.openai.com/api/docs/guides/live-delegation documents structured function calls through Responses delegation.
