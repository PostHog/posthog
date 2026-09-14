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

Django posts to `{WIZARD_GATEWAY_URL}/v1/tokens` with
`Authorization: Bearer {WIZARD_GATEWAY_MINT_KEY}`:

| Field             | Meaning                                     |
| ----------------- | ------------------------------------------- |
| `cap_usd`         | Fixed-point spend ceiling for this token    |
| `ttl_seconds`     | Token lifetime, clamped to 1800-86400       |
| `product`         | Product node, `wizard:<program id>`         |
| `obo`             | The organization the spend is attributed to |
| `user`            | The user the run belongs to                 |
| `allowed_models`  | Models this token may reach                 |
| `allowed_efforts` | Reasoning efforts this token may declare    |

`allowed_models` and `allowed_efforts` come from `WIZARD_MODEL_ALLOWLIST`, which
is the canonical table. The wizard CLI's own model constants follow that table
rather than the other way round. A gateway that predates either field ignores it
and mints an unpinned token, so Django can send both before the gateway enforces
them.

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

Mints are metered per user, per program, per week. The reservation is atomic and
charged immediately before the mint, so a run refused by an earlier gate spends
nothing, and a failure that proves no token was issued returns the slot.

A value rejected as out of contract is logged and counted on
`posthog_wizard_gateway_config_rejects_total{field}`, because the mint otherwise
degrades toward a floor with nothing to alert on.

## Refusals

The endpoint answers one outcome per request, counted on
`posthog_wizard_gateway_token_requests_total{outcome}`: `unconfigured`,
`invalid_token`, `not_wizard_app`, `scope_missing`, `team_ambiguous`,
`team_missing`, `unauthorized`, `blocked`, `not_rolled_out`, `program_unknown`,
`throttled`, `mint_failed`, or `minted`.

Refusals that an older CLI absorbed by falling back to the legacy gateway
(`unconfigured`, `not_rolled_out`, `program_unknown`) answer 403 with a reason
only to a client that sent `reads_refusal_reason: true`. Any other client still
receives 404, which is the signal its fallback depends on. That branch retires
once those builds are gone.
