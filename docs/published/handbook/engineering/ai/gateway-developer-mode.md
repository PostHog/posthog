---
title: Calling the AI gateway from your machine
sidebar: Docs
showTitle: true
---

Developer mode gives PostHog staff a short-lived AI gateway token (`phe_`) for local work: Claude Code, scripts, evals, and SDK experiments.
Use it instead of a project secret key (`phs_`). A `phs_` key never expires, and calls made with a shared one have no user attached, so nobody can tell who spent what.

Production services keep calling the gateway through `get_llm_client(product=..., team_id=...)` or their own `phs_` key. This page is for calls a person runs from their own machine.

## Limits

|                  |                                   |
| ---------------- | --------------------------------- |
| Token lifetime   | 8 hours                           |
| Spend per token  | $25                               |
| Spend per person | $50 of minted tokens per 24 hours |
| Billed to        | PostHog's own project             |
| Region           | US only                           |

Every call is attributed to you (`$ai_user` is your distinct id, `$ai_product` is `dev`), and its prompts are reviewable: privacy mode is refused for these tokens.

## Get a token

From the web app: go to [Settings → AI gateway developer mode](https://us.posthog.com/settings/user-ai-gateway-dev-mode) and create a token. The token is shown once.

From a terminal:

```bash
export ANTHROPIC_API_KEY=$(hogli gateway:token)
```

`hogli gateway:token` opens the same settings page to approve the request, then prints only the token to stdout, so `$(...)` captures it. The expiry and cap go to stderr.

## Use it

The gateway is at `https://ai-gateway.us.posthog.com`. Pass the `phe_` token wherever an SDK expects an API key.

### Claude Code

```bash
export ANTHROPIC_BASE_URL=https://ai-gateway.us.posthog.com
export ANTHROPIC_API_KEY=$(hogli gateway:token)
claude
```

### Anthropic SDK

The base URL has no `/v1`; the SDK appends `/v1/messages`.

```python
from anthropic import Anthropic

client = Anthropic(base_url="https://ai-gateway.us.posthog.com", api_key="phe_...")
client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "hello"}],
)
```

### OpenAI SDK

The base URL includes `/v1`.

```python
from openai import OpenAI

client = OpenAI(base_url="https://ai-gateway.us.posthog.com/v1", api_key="phe_...")
client.chat.completions.create(
    model="gpt-5.4-mini",
    messages=[{"role": "user", "content": "hello"}],
)
```

`client.responses.create(...)` works too.

### Google GenAI SDK

```python
from google import genai
from google.genai import types

client = genai.Client(
    api_key="phe_...",
    http_options=types.HttpOptions(base_url="https://ai-gateway.us.posthog.com"),
)
client.models.generate_content(model="gemini-3-flash-preview", contents="hello")
```

`GET https://ai-gateway.us.posthog.com/v1/models` lists every model the gateway serves.

### What a `phe_` token can't do

- Call anything other than model and token-count endpoints. Gemini files, caches and uploads, `/v1/usage`, `/v1/wallet/balance` and `/v1/tokens/*` return `403`.
- Change its attribution. `X-PostHog-Product`, `X-PostHog-User`, `X-PostHog-Obo` and `X-PostHog-Distinct-Id` are ignored, and the response names them on `X-PostHog-Token-Warnings`. Session, trace and custom-property headers still work.
- Turn on privacy mode.

The full header and endpoint reference is the gateway's [`docs/api.md`](https://github.com/PostHog/ai-gateway/blob/main/docs/api.md).

## Check what's left

```bash
hogli gateway:status
```

It reads the token from stdin, or from `POSTHOG_GATEWAY_TOKEN`, `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` (the first one holding a `phe_` value), and prints what is left of the cap and when the token expires. It never takes the token as an argument, so it stays out of shell history.

The settings page shows the same numbers in the "Left" column of your token list.

## When a call fails

| Status                   | Meaning                                          | What to do                                           |
| ------------------------ | ------------------------------------------------ | ---------------------------------------------------- |
| `401`                    | The token expired or was revoked                 | Get a new token                                      |
| `402 token_cap_exceeded` | The token spent its $25                          | Get a new token                                      |
| `429` on mint            | You've minted $50 of tokens in the last 24 hours | The error says when you can mint again               |
| `403` on a call          | The endpoint isn't open to `phe_` tokens         | Use a model endpoint, or a `phs_` key from a backend |

## If a token leaks

Revoke it from the settings page. A leaked token can spend at most what is left of its cap before it expires.
