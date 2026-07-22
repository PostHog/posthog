"""Stripe Projects provisioning API - Agentic Provisioning Protocol (APP) 0.1d.

Provider endpoints for the Stripe orchestrator, mounted under
``/api/partners/stripe/``: account requests, token exchange, resource
provisioning, service updates, credential rotation, and deep links.

Spec: https://github.com/agentic-provisioning/posthog-spec/blob/master/docs/spec.md

Auth codes and deep links live in the shared cache and are interoperable with
the other provisioning surfaces: codes minted by the interactive consent flow
(``/api/agentic/authorize``) are redeemed at this namespace's token endpoint,
and deep links minted here are consumed by ``/agentic/login``. The literals
below define those cache keys - treat them as a cross-surface contract.
"""

AUTH_CODE_CACHE_PREFIX = "provisioning_auth_code:"

DEEP_LINK_CACHE_PREFIX = "provisioning_deep_link:"
