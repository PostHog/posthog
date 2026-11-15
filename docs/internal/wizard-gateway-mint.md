# Wizard gateway mint

The wizard CLI does not hold a long-lived model credential. It calls
`POST /api/wizard/gateway_token/` once per run, Django decides what that run may
spend and reach, and Django mints a short-lived scoped token from the Go
ai-gateway. Every limit below is applied at mint time, so a token that is already
issued carries its own ceiling and cannot be widened by a later request.

Code: `posthog/api/wizard/http.py` (the endpoint and its gates),
`posthog/llm/wizard_gateway_token.py` (posture, limits, and the mint call),
`posthog/rate_limit.py` (the mint reservation).

## Mint request

The CLI sends `program` and `reads_refusal_reason: true` to `POST /api/wizard/gateway_token/`.
`reads_refusal_reason` controls whether a refusal that an older CLI absorbed uses 403 with a reason or the legacy 404 response.
Django attaches the operator system prompt to the token whenever the prompt flag is usable.
The client never sees the prompt and sends none: the gateway injects it into every model request.

Django posts to `{WIZARD_GATEWAY_URL}/v1/tokens` with
`Authorization: Bearer {WIZARD_GATEWAY_MINT_KEY}`:

| Field             | Meaning                                                            |
| ----------------- | ------------------------------------------------------------------ |
| `cap_usd`         | Fixed-point spend ceiling for this token                           |
| `ttl_seconds`     | Token lifetime, clamped to 1800-86400                              |
| `product`         | Product node, `wizard:<program id>`                                |
| `obo`             | The organization the spend is attributed to                        |
| `user`            | The user the run belongs to                                        |
| `allowed_models`  | Models this token may reach                                        |
| `allowed_efforts` | Reasoning efforts this token may declare                           |
| `system_prompt`   | The operator prompt text, sent only when the prompt flag is usable |

The pins come from two flags in the PostHog internal project,
read once per mint request after authentication.

- `wizard-ai-gateway-system-prompt` is read from local evaluation only, so the read adds no network time to the mint.
  The read sends `$feature_flag_called`.
  The payload is `{"text": "<prompt>"}`, plus an optional `"version"` that is the operator's own label and that nothing reads.
  The text is non-empty, at most 16384 bytes, valid UTF-8 without U+FFFD, and contains `[posthog:abort]`.
  It goes to the gateway as `system_prompt`, byte for byte.
- `wizard-gateway-allowlist`: `{"models": [...], "efforts": [...], "programs": [...]}`.
  All three lists are non-empty, and `efforts` come from the gateway's effort vocabulary.
  `models` holds at most 32 entries, and each one must still name a model after the mint strips the `openai/` prefix.
  The read carries the `email`, `organization_id` and `team_id` person properties the limit-override flag gets.
  They matter only if the allowlist is a regular boolean flag with release conditions instead.

The mint response carries no prompt field at all, pinned or not: no text and no version.
Nothing logs the prompt text, and no error returns it.
A policy flag never refuses a mint:

- A prompt flag that is missing, unreadable or out of contract mints an unpinned token. The mint body omits
  `system_prompt`. The operator kill switch is turning the flag off, clearing the payload, or deleting the flag.
- An allowlist flag that is unreadable or out of contract falls back to `WIZARD_DEFAULT_MODELS`,
  `WIZARD_DEFAULT_EFFORTS` and `WIZARD_DEFAULT_PROGRAMS` in `wizard_gateway_token.py`.
- Unreadable payloads, flags that return no payload, and out-of-contract payloads log a warning. The PostHog SDK
  swallows its own errors and returns no payload, so an outage reads the same as a flag with no payload.
  Out-of-contract ones also count on
  `posthog_wizard_gateway_config_rejects_total{field="system_prompt"|"allowlist"}`.

A gateway that predates a field ignores it and mints a token without it.
The `programs` list is authoritative: a program absent from it is refused as `program_unknown`.

## Limits

A mint resolves an organization's posture first: `new` (younger than 7 days with
no ingested event), `active` (has ingested an event), or `paid`. The posture
picks a tier of `cap_usd`, `max_cap_usd`, `mints_per_week`, and `ttl_seconds`
from `WIZARD_GATEWAY_TIERS`, falling back per field to the in-code floor for that
posture rather than to the flat setting, whose cap is wider than every tier.

The cap resolves in order: the limit-override flag, then the program's own cap
bounded by the posture's ceiling, then the posture's cap, then
`WIZARD_GATEWAY_TOKEN_CAP_USD`. The flat setting applies only when no posture
resolved. Every value passes a contract check bounded by `_MAX_CAP_USD`.

Mints are metered per user, per week — one bucket across every program, so the
tier's count is the hard per-account ceiling. The reservation is atomic and
charged immediately before the mint, so a run refused by an earlier gate spends
nothing, and a failure that proves no token was issued returns the slot.

A value rejected as out of contract is logged and counted on
`posthog_wizard_gateway_config_rejects_total{field}`, because the mint otherwise
degrades toward a floor with nothing to alert on.

## Refusals

The endpoint answers one outcome per request, counted on
`posthog_wizard_gateway_token_requests_total{outcome}`: `unconfigured`,
`invalid_token`, `not_wizard_app`, `scope_missing`, `team_ambiguous`,
`team_missing`, `unauthorized`, `blocked`, `program_unknown`,
`throttled`, `mint_failed`, or `minted`.

Refusals that an older CLI absorbed by falling back to the legacy gateway
(`unconfigured`, `program_unknown`) answer 403 with a reason
only to a client that sent `reads_refusal_reason: true`. Any other client still
receives 404, which is the signal its fallback depends on. That branch retires
once those builds are gone.
