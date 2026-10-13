# SNS

Deliveries from an AWS SNS HTTPS subscription.

## Headers

None.
SNS signs the message itself, so this incarnation reads no header.
The envelope fields `Type`, `MessageId` and `TopicArn` all come from the JSON body.

## Signature scheme

Not HMAC.
`SnsSignature` checks two things and needs both.
The message signature proves the message is from SNS: an RSA-SHA256 check over AWS's canonical string-to-sign, against a certificate fetched from a `sns.<region>.amazonaws.com` URL of the one shape SNS serves.
That half is the same for every SNS topic, so it lives in the verify lane (`verify/sns_signature.py`) with its certificate cache, its failure cache, and a per-minute budget on fetches for URLs that have never verified a message.
A certificate that could not be obtained raises `VerifierUnavailable`, and the scheme answers `UNAVAILABLE`, so the view replies 503 and SNS delivers again.
A certificate URL that fails the host and path check is a bad signature rather than an unavailable verification, and it is never fetched.
Only `SignatureVersion` 2 is accepted; a topic left on version 1 has every delivery rejected, logged as a misconfiguration rather than an attack.
The `TopicArn` allowlist proves the message is from our topic.
An empty allowlist reads as unconfigured, which answers 404 with an empty body and logs a warning, so a probe of this public URL learns nothing and cannot flood the error logs.
A body that is not a JSON object is invalid, and there is no replay window.

## Delivery id and event type

The delivery id is the body's `MessageId`.
The event type is the body's `Type`: `SubscriptionConfirmation`, `Notification` or `UnsubscribeConfirmation`.
The `TopicArn` goes into the delivery context.

## Apps and secrets

One app, `default`, and no secret: SNS signs with its own certificate, so there is nothing for an operator to hold.
The topic allowlist is the only per-endpoint configuration, so `build_sns_provider()` takes the name of the Django setting that holds it and reads it per request.
The SES events endpoint names `WORKFLOWS_SES_EVENTS_SNS_TOPIC_ARNS`.

## Quirks

The subscription handshake is an event type, not a pre-dispatch response.
Confirming a subscription means calling AWS back, which is a consumer's business rather than the transport's, so a consumer registers for `SubscriptionConfirmation` separately from `Notification`.
An unknown topic logs `ingress_sns_unknown_topic` and answers like a bad signature.
SNS retries a delivery on a non-2xx, so this incarnation sets `retry_status` to 502.
A delivery no consumer accepted is then not receipted, which is what lets a failed confirmation callback be tried again.

## Consumers

`workflows_ses_events`, on the `default` app, for `SubscriptionConfirmation` and `Notification`.
See the [Endpoints table](../README.md#endpoints).
