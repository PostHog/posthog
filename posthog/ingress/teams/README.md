# Microsoft Teams

Bot Framework activities from Azure Bot Service, for the SupportHog Teams bot.

## Headers

- `Authorization` carries the bearer token, as `Bearer <jwt>`. There is no signature header.

## Signature scheme

`BearerJwt`, against the signing keys Bot Framework publishes.
The accepted algorithms are RS256, RS384 and RS512, which is what the Bot Framework OpenID metadata document lists.
A token must carry `exp`, and the clock leeway is 300 seconds.

The three values the scheme needs are getters the product supplies, because the bot registration is the product's:

- **The signing-key URI.** Bot Framework publishes `jwks_uri` inside its OpenID metadata document rather than at a fixed path, so the getter fetches that document, caches the result for an hour, and passes the discovered URI through `is_url_allowed` before returning it. The URI is a third party's value rather than an operator's, so it is guarded the way `posthog/api/id_jag.py` guards its own discovered JWKS URI.
- **The audience**, which is the bot's app id from instance settings.
- **The issuers**, which is `https://api.botframework.com` alone. The Azure AD issuer variants sign with keys that live in another JWKS, so a token carrying one of them could never verify here anyway.

A JWKS fetch that fails on transport answers `UNAVAILABLE` and the view answers 503, so Bot Framework redelivers rather than losing the activity to a 403.

The endpoint sits behind `TeamsEventWebhookThrottle`, a per-IP cap from `posthog.rate_limit`.
It runs in front of verification, because the first thing an unsigned request would otherwise buy is a signing-key lookup.

## Delivery id and event type

The delivery id is the activity's `id`, which Bot Framework repeats across every retry of one activity, so dedup keys on it.
The event type is the activity's `type`, so a consumer registers for `message` or `conversationUpdate`.

The context carries the two verified claims: `claim_service_url` (the `serviceurl` claim) and `claim_tenant_id` (the `tid` claim).
Both already equal the activity body, because an activity where they do not never becomes a delivery, so a consumer may read either.
The token never reaches the context, because a consumer's context travels into its logs and its receipts.
`tid` is absent on Bot Framework channels other than Teams, so it is an empty string there.

## Apps and secrets

One app, `supporthog`.
This incarnation holds no secret: everything about the bot registration arrives through the three getters `build_teams_provider()` takes.
Nothing under `posthog/ingress/` reads instance settings for it.

## Quirks

**The body repeats what the token signs, and `deliveries()` refuses the activity when the two disagree.**
`serviceUrl` and `channelData.tenant.id` are plain JSON, so a caller holding any valid Bot Framework token could otherwise attribute an activity to another tenant, or steer the bot's outbound bearer token at a host of its choosing.

Microsoft's connector authentication requires the `serviceurl` claim to be present and to equal the activity's `serviceUrl`, and its own SDKs compare the two as strings without regard to case.
So a token that carries no `serviceurl` claim, and an activity whose `serviceUrl` the claim does not equal, are both `InvalidPayload`: 400, before ownership and before any consumer runs.
The comparison ignores case and a trailing slash, which Teams sends in the body and not in the claim.
`tid` is not one of Microsoft's validation rules, so it is checked when both sides carry it rather than required.

**The signing key has to be endorsed for the channel the activity names.**
One JWKS signs every Bot Framework channel, and each key lists the channels it may sign for in an `endorsements` member that `BearerJwt` carries into the facts.
Microsoft's rule is that a bot holds an activity's `channelId` to an endorsement on the key that signed it, and rejects the activity when that endorsement is absent.
This app serves Teams alone, so `deliveries()` refuses anything but an activity whose `channelId` is `msteams`, signed by a key whose endorsements include `msteams`.
A key with no `endorsements` member is refused for the same reason, and no key Bot Framework publishes omits it.

Without that, a token minted for another channel of the same bot registration carries the audience and the issuer the scheme requires, and the activity body alone would decide which tenant the message is attributed to.
Microsoft answers this one with 403 and ingress answers it with the 400 it gives any refused body, which has the same effect: no consumer runs, and Bot Framework does not retry a 4xx.

The `InvalidPayload` message names the field and never either value, because it lands in the log of an endpoint a stranger can drive.

What stays with the consumer is the host allowlist: the claim proves Microsoft signed that URL, not that the URL is one of Microsoft's Bot Framework endpoints, and the consumer is what sends the bot's token to it.

**An unset app id answers 403, and a signing-key URI the getter could not discover answers 503.**
403 is `unconfigured_status`, not the package default of 500, and is the status the hand-rolled view answered.
It keeps an instance that never registered a bot from turning every anonymous probe of a public URL into a server error.
`explains_rejections` is False with it, so neither that answer nor a rejected token names its reason. Bot Framework reads the status alone.

The two cases have to stay apart, because `jwks_uri_getter` fetches Microsoft's OpenID metadata document and answers `None` when that fetch fails.
`BearerJwt` reads the audience and the issuers first and answers `NOT_CONFIGURED` for those, then reads the URI and answers `UNAVAILABLE` when it is missing.
Bot Framework retries a 5xx for about ten minutes and does not retry a 403, so folding the failed fetch into the 403 would lose every activity for the length of a Microsoft outage.
Checking the audience first also means an instance with no bot registration buys no metadata fetch.

**Two certification paths must run in this region and must never be forwarded.**
The Teams Store certification requires a reply to a command message such as "help" even from a tenant that never finished OAuth, and a proactive welcome when the bot is added to a conversation.
Neither needs a tenant that PostHog knows, so the consumer answers `UNDECIDED` for both and the delivery runs here exactly once.
A regular message from a tenant the other region holds answers `ELSEWHERE`, and the local run of that delivery is a no-op.

**The tenant lookup runs under a bounded statement timeout, and a lookup that spends it raises rather than answering.**
The dispatcher records that as `FAILED`, so the view answers 503 before the forward and before any consumer runs, and Bot Framework sends the activity again.
Answering `ELSEWHERE` through a timeout would be a guess, because a lookup that never finished rules no region out, and the forward would carry the customer's message content into a region that may not hold the tenant.
This is also what the handler before ingress did: it proxied to the other region only when the local lookup found no team, and a lookup that raised cost the request its receipt.

**Bot Framework retries an activity for about ten minutes on a 5xx or a timeout, with the same activity id.**
So `retry_status` is 503: a forward that never landed, an ownership lookup that did not answer, or a handoff that raised, must not be receipted.
Every other status code is the default.

## Consumers

`conversations_teams`, on the `supporthog` app, for `message` and `conversationUpdate`.
It declares `ownership`, so a regular message about a tenant the other region holds is forwarded there.
See the [Endpoints table](../README.md#endpoints).
