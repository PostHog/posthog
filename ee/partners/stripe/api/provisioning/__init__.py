"""Stripe Projects provisioning API - Agentic Provisioning Protocol (APP) 0.1d.

Provider endpoints for the Stripe orchestrator, mounted under
``/api/partners/stripe/``: account requests, token exchange, resource
provisioning, service updates, credential rotation, and deep links.

Spec: https://github.com/agentic-provisioning/posthog-spec/blob/master/docs/spec.md

Both cache keys are Stripe-specific and deliberately NOT interoperable with the
other provisioning surfaces: auth codes are minted and redeemed within this
namespace, and deep links are minted by ``DeepLinksView`` and consumed by this
namespace's own login route (``login.py``), not the legacy ``/agentic/login``.
"""

AUTH_CODE_CACHE_PREFIX = "stripe_provisioning_auth_code:"

DEEP_LINK_CACHE_PREFIX = "stripe_provisioning_deep_link:"
