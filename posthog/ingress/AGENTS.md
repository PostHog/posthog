# Inbound webhook verification & dispatch

Read the README before adding a provider, changing a scheme, or touching the registry.
Read a provider's own `README.md` before changing that provider, and invoke `/adding-inbound-webhooks` before adding or changing a provider.
Three things are easy to re-derive wrong: the response is a transport receipt (a consumer's return value never decides the status, though a provider that sets `retry_status` is not receipted when the work did not run), a consumer's `name` is a dedup cache key (renaming one lets a redelivery run twice), and nothing here may import a product — product-owned secrets and verifiers are passed into the provider builder.

@README.md
