# Inbound webhook verification & dispatch

Read the README before adding a provider, changing a scheme, or touching the registry.
Read a provider's own `README.md` before changing that provider.
A change to a provider's headers, signature scheme, delivery id, apps and secrets, or consumers updates that provider's `README.md` in the same PR.
A provider folder without a `README.md` fails `posthog/ingress/test/test_provider_readme_sections.py`.
Three things are easy to re-derive wrong: the response is a transport receipt (a consumer never decides the status), a consumer's `name` is a dedup cache key (renaming one lets a redelivery run twice), and nothing here may import a product — product-owned secrets and verifiers are passed into the provider builder.

@README.md
