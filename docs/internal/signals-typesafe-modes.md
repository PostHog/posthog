# TypeSafe decision modes in signals

The `signals-typesafe-mode` server-side multivariate feature flag controls the actionability, signal safety, and report safety decisions:

| Variant              | Deciding model | Other model                   |
| -------------------- | -------------- | ----------------------------- |
| `traditional-only`   | Existing LLM   | None (default)                |
| `typesafe-shadow`    | Existing LLM   | TypeSafe runs in parallel     |
| `traditional-shadow` | TypeSafe       | Existing LLM runs in parallel |
| `typesafe-only`      | TypeSafe       | None                          |

Both shadow modes record verdict differences. A TypeSafe error in `typesafe-shadow` leaves the existing LLM verdict in control. In `traditional-shadow`, a TypeSafe error falls back to the existing LLM and records the fallback. In `typesafe-only`, a TypeSafe error fails the decision; existing activity retry and failure handling apply. A flag-read error or unknown variant uses `traditional-only`.

The flag is evaluated for `team-{team_id}` with a `project` group whose `id` is the team ID. It has no effect until both `SIGNALS_TYPESAFE_CLOUDFLARE_ACCOUNT_ID` and `SIGNALS_TYPESAFE_CLOUDFLARE_API_TOKEN` are set. Use a dedicated Cloudflare token with Account > Workers AI > Read permission; do not widen or reuse the proxy-provisioning token. The token and account ID must be provisioned separately in each environment. Set the flag's default variant to `traditional-only`.

Jev uses the `typesafe/jev` model through Cloudflare's `POST /accounts/{account_id}/ai/run` endpoint. The request retains the same state and question text used by the local evals. Safety requests add a `choice` question for the five block categories and `none` to the same state and API call. The actionability threshold is 0.95, signal safety is 0.90, and report safety is 0.50. These thresholds produce a TypeSafe verdict when it decides and produce comparison telemetry in shadow mode. An unsafe TypeSafe verdict has a category and a generic explanation; Jev does not supply a quoted fragment.

The `signals_typesafe_decision_evaluated` event contains mode, deciding provider, stage, source identity, both verdicts, disagreement, safety category and confidence, Jev probability and model version, each call's latency and status, Jev token usage, and a direct TypeSafe list-price estimate. Signal safety also records category disagreement with the traditional model. The event contains no prompt or signal text. Prometheus metrics `signals_typesafe_decision_calls_total`, `signals_typesafe_decision_disagreements_total`, `signals_typesafe_decision_latency_seconds`, `signals_typesafe_decision_input_tokens_total`, and `signals_typesafe_decision_direct_list_cost_usd_total` support trends and alerts. The existing `$ai_generation` events retain traditional-model spend by `ai_stage`.

The Jev cost estimate uses TypeSafe's published direct price of $0.042 per million input tokens. Cloudflare directs users to its dashboard for this model's price, so the estimate is **not a Cloudflare bill**. Compare Cloudflare billing with token totals before using it for savings decisions. `SIGNALS_TYPESAFE_CLOUDFLARE_REQUESTS_PER_MINUTE` defaults to 20; raise it only after confirming the account's actual model limit and billing mode. The outbound limiter sheds shadow calls when its `BATCH` allowance is exhausted.

Cloudflare lists Jev as a **third-party** model. Its API can route the request, but its documentation does not establish that TypeSafe does not process customer content. Cloudflare availability alone does not settle the subprocessor question. Confirm the data flow and agreement before enabling this flag for customer data. Amazon Bedrock's published model catalog does not list Jev as of September 18, 2026.

Sources: [Cloudflare Jev model and API](https://developers.cloudflare.com/ai/models/typesafe/jev/), [Cloudflare AI routing](https://developers.cloudflare.com/ai-gateway/usage/rest-api/), [Cloudflare model catalog](https://developers.cloudflare.com/ai/models/), [Cloudflare Workers AI limits](https://developers.cloudflare.com/workers-ai/platform/limits/), [AWS Bedrock model availability](https://docs.aws.amazon.com/bedrock/latest/userguide/models-region-compatibility.html), [TypeSafe introduction and price](https://typesafe.ai/blog/introducing-system-one-models-and-jev).
