# SNS

Deliveries from an AWS SNS HTTPS subscription.

## Headers

None.
SNS signs the message itself, so this incarnation reads no header.
The envelope fields `Type`, `MessageId` and `TopicArn` all come from the JSON body.

## Signature scheme

Not HMAC.
`SnsSignature` checks two things and needs both.
The message signature proves the message is from SNS, through a verifier the caller supplies, which owns the certificate fetch and its own cache.
The `TopicArn` allowlist proves the message is from our topic.
An empty allowlist reads as unconfigured.
A body that is not a JSON object is invalid, and there is no replay window.

## Delivery id and event type

The delivery id is the body's `MessageId`.
The event type is the body's `Type`: `SubscriptionConfirmation`, `Notification` or `UnsubscribeConfirmation`.
The `TopicArn` goes into the delivery context.

## Apps and secrets

One app, `default`, and no secret.
The verifier and the topic allowlist belong to whoever owns the topic, so `build_sns_provider()` takes both as callables.

## Quirks

The subscription handshake is an event type, not a pre-dispatch response.
Confirming a subscription means calling AWS back, which is a consumer's business rather than the transport's, so a consumer registers for `SubscriptionConfirmation` separately from `Notification`.
An unknown topic logs `ingress_sns_unknown_topic` and answers like a bad signature.

## Consumers

No product registers an SNS consumer yet.
The workflows SES events endpoint moves to ingress in its own PR.
See the [Endpoints table](../README.md#endpoints).
