"""Fire-and-forget dispatch of the signup enrichment workflow from the request path.

Every guard lives here so the signup serializer stays a one-line call. Dispatch is
gated by the kill switch, US-only for v0, and a configured Harmonic key, and never
raises — a Temporal outage degrades to "enrichment did not run". Personal-domain
signups get no provider lookup, but the work-vs-personal email signal is recorded
for every signup so consumers can read it either way.
"""

import asyncio

from django.conf import settings
from django.db import transaction

import structlog
from temporalio.common import WorkflowIDReusePolicy
from temporalio.service import RPCError

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.client import sync_connect
from posthog.temporal.signup_enrichment.workflow import SignupEnrichmentInputs
from posthog.utils import GenericEmails, get_instance_region

from products.growth.backend.enrichment.writer import record_signup_work_email

logger = structlog.get_logger(__name__)

_generic_emails = GenericEmails()


def _domain_from_email(email: str) -> str | None:
    if not email or "@" not in email:
        return None
    domain = email.rsplit("@", 1)[1].strip().lower()
    return domain or None


def start_signup_enrichment_workflow(*, organization_id: str, distinct_id: str | None, email: str) -> None:
    """Dispatch enrichment for a freshly signed-up org, once the request transaction commits."""
    if not settings.GROWTH_SIGNUP_ENRICHMENT_ENABLED or not settings.HARMONIC_API_KEY:
        return
    # v0 is US-only.
    if get_instance_region() != "US":
        return

    domain = _domain_from_email(email)
    if not domain:
        return

    work_email = not _generic_emails.is_generic(email)
    _record_work_email(organization_id=str(organization_id), work_email=work_email)
    if not work_email or not distinct_id:
        return

    inputs = SignupEnrichmentInputs(organization_id=str(organization_id), distinct_id=distinct_id, domain=domain)
    # on_commit so the worker never reads the org/enrichment rows before they are committed;
    # fires inline when no transaction is open.
    transaction.on_commit(lambda: _dispatch(inputs))


def _record_work_email(*, organization_id: str, work_email: bool) -> None:
    # The write runs in its own savepoint; a failure here must never surface to signup.
    try:
        record_signup_work_email(organization_id=organization_id, work_email=work_email)
    except Exception as e:
        capture_exception(e)


def _dispatch(inputs: SignupEnrichmentInputs) -> None:
    try:
        client = sync_connect()
        asyncio.run(
            client.start_workflow(
                "signup-enrichment",
                inputs,
                id=f"signup-enrichment-{inputs.organization_id}",
                task_queue=settings.GENERAL_PURPOSE_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
        )
    except RPCError as e:
        # A duplicate id (re-signup race) or transient RPC issue must not surface to signup.
        logger.info("signup_enrichment_dispatch_skipped", organization_id=inputs.organization_id, error=str(e))
    except Exception as e:
        capture_exception(e)
