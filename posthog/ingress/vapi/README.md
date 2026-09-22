# Vapi

Deliveries from the Vapi voice agent.

## Headers

- `X-Vapi-Signature` carries the signature.

Vapi sends no delivery header and no timestamp header.

## Signature scheme

HMAC-SHA256 over the raw body, hex encoded, with no prefix.
There is no replay window, because there is no timestamp to check.
A signature that is not 64 lowercase hex characters is rejected before the HMAC runs, which keeps a casual probe off the digest path.

## Delivery id and event type

Vapi sends no delivery id, so dedup is skipped.
The call id is the only stable id in the payload, and it repeats across the status update and the end-of-call report.
It therefore cannot key dedup: a mark set by the first message would swallow the second.
The call id goes into the delivery context as `call_id`, and the consumer stays idempotent on it.
The event type is `message.type`.

## Apps and secrets

One app, `default`.
The secret is the Django setting `VAPI_WEBHOOK_SECRET`.

## Quirks

A bad signature answers 401 and an unconfigured instance answers 503.
The public interview surface already relies on both codes.

A delivery a consumer did not accept answers 500 rather than the 202 receipt, because Vapi sends the delivery again after a 5xx.
The report is the only copy of an interview, so losing it to a receipt costs the transcript.

The provider sets `throttle_class` to `VapiWebhookIPThrottle`, a per-IP cap of 1200/minute from `posthog/rate_limit.py`.
The endpoint is public and unauthenticated, so the cap bounds how much HMAC-verification CPU and structured-log volume one source can drive.
Vapi's egress is shared across all tenants, so the bucket sits well above legitimate aggregate volume: a busy interview hour must not bleed onto a normal one.
The refusal is the shared lane's 429 with a `Retry-After`.

## Consumers

One consumer, `user_interviews_vapi`, declared in `products/user_interviews/backend/webhook_consumers.py`.

It enqueues a Celery task and returns, so the request does not wait on persistence.
The enqueue is the only work on the request path, so a failure there is what the 500 above answers.
The task persists the end-of-call report and retries a transient database error, so a lost connection does not lose the transcript.
It acknowledges late, so a worker that dies mid-task gives the report back to the broker.
The handler is idempotent on the call id, which is what makes both the retry and the redelivery safe.
