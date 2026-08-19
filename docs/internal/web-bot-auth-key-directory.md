# Web Bot Auth key directory

PostHog Cloud US serves the Web Bot Auth key directory at `/.well-known/http-message-signatures-directory`.
The directory publishes the public keys for `PostHogSessionReplayBot` and signs each response with the corresponding private keys.

## Configuration

Set `WEB_BOT_AUTH_PRIVATE_KEYS` to a comma-separated list of unencrypted Ed25519 private keys in PKCS8 PEM format.
Encode PEM line breaks as literal `\n` sequences when the secret store requires a single-line value.
During key rotation, include the old and new keys until consumers have accepted the new key.

Leave the variable unset outside PostHog Cloud US.
The endpoint returns `404` when the variable is unset or the deployment is not in the US region.

When the variable is present, each production ASGI worker schedules validation on a daemon thread during lifespan startup.
An empty or invalid value does not stop startup.
PostHog Error Tracking receives a sanitized configuration error, and the endpoint returns `503` without exposing key material.

## Outbound request signing

The Node.js image fetch lane reads the same variable and signs each outbound request with every configured key.
It signs each redirect hop for that hop's authority.
The signatures expire after one minute and include a unique 64-byte nonce.

The request uses the structured-string `Signature-Agent` format in [Cloudflare's current verifier](https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/).
It includes the parameters required by the [current Web Bot Auth protocol draft](https://datatracker.ietf.org/doc/draft-meunier-webbotauth-httpsig-protocol/).
