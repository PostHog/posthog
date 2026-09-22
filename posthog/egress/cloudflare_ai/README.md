# Cloudflare AI egress

## Identity

The Cloudflare account ID owns the model request limit. It is a non-secret account identifier.

## Budget

The default is an operator ceiling of 20 requests per minute per account, not a published Jev limit.
The direct transport does not use Cloudflare AI Gateway, so AI Gateway prepaid-credit limits do not apply automatically.
Change `SIGNALS_TYPESAFE_CLOUDFLARE_REQUESTS_PER_MINUTE` only after confirming the `typesafe/jev` limit for the configured billing path.
Calls use the sheddable `BATCH` lane.
An exhausted budget leaves the traditional verdict in control in either shadow mode; the TypeSafe-only mode fails the decision.

## Lanes and callers

The signals actionability, signal safety, and report safety calls use `BATCH`. The default lane reserve remains in place.

## Rate-limit headers

No rate-limit response headers are parsed; the published limits are enforced by the local budget.

## Auth

A dedicated Cloudflare API token with Account > Workers AI > Read permission is supplied by the caller. The existing proxy provisioner token is not reused.

## Sources

- [Cloudflare Jev model and API](https://developers.cloudflare.com/ai/models/typesafe/jev/)
- [Cloudflare AI API authentication](https://developers.cloudflare.com/ai-gateway/usage/rest-api/)
- [Workers AI limits](https://developers.cloudflare.com/workers-ai/platform/limits/)
