# Inbound webhook verification & dispatch

Read the README before adding a provider, changing a scheme, or touching the registry.
Three things are easy to re-derive wrong: the response is a transport receipt (a consumer never decides the status), a consumer's `name` is a dedup cache key (renaming one lets a redelivery run twice), and nothing here may import a product — product-owned secrets and verifiers are passed into the provider builder.

@README.md
