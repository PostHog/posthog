"""Fire-and-forget dispatch of the signup enrichment workflow from the request path.

Every guard lives here so the signup serializer stays a one-line call. Dispatch is
gated by the kill switch and US-only for v0, and never raises — a Temporal outage
degrades to "enrichment did not run". The provider key lives on the workers only. Personal-domain
signups get no provider lookup, but the work-vs-personal email signal is recorded
for every signup so consumers can read it either way.
"""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from email.utils import parseaddr

from django.conf import settings
from django.db import transaction

import structlog
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.client import sync_connect
from posthog.temporal.signup_enrichment.workflow import SignupEnrichmentInputs
from posthog.utils import GenericEmails, get_instance_region

from products.growth.backend.enrichment.writer import record_signup_work_email

logger = structlog.get_logger(__name__)

_generic_emails = GenericEmails()

# Bounded dispatch pool: a slow or unreachable Temporal must never let signup-triggered
# threads accumulate on web pods. When the pool's backlog cap is hit, dispatch drops —
# fire-and-forget degrades to "enrichment did not run", which the launch signal surfaces.
_DISPATCH_MAX_WORKERS = 4
_DISPATCH_MAX_PENDING = 64
_dispatch_executor = ThreadPoolExecutor(
    max_workers=_DISPATCH_MAX_WORKERS, thread_name_prefix="signup-enrichment-dispatch"
)
_dispatch_slots = threading.BoundedSemaphore(_DISPATCH_MAX_PENDING)


def _domain_from_email(email: str) -> str | None:
    _, address = parseaddr(email or "")
    if "@" not in address:
        return None
    domain = address.rsplit("@", 1)[1].strip().lower()
    return domain or None


def start_signup_enrichment_workflow(*, organization_id: str, distinct_id: str | None, email: str) -> None:
    """Dispatch enrichment for a freshly signed-up org, once the request transaction commits."""
    # The flag alone gates dispatch. Deliberately no provider-key check here: the key lives
    # only on the workers, and a keyless worker fails loudly into the launch alert instead of
    # web pods silently never dispatching (also keeps the key off the public web fleet).
    if not settings.GROWTH_SIGNUP_ENRICHMENT_ENABLED:
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
    # on_commit so the worker never reads the org/enrichment rows before they are committed. The
    # callback fires inline on the signup request thread (it runs after that transaction commits),
    # so dispatch goes to the bounded pool: building the Temporal client must not add latency to
    # the signup response, and the pool caps how much a Temporal outage can pile up.
    transaction.on_commit(lambda: _submit_dispatch(inputs))


def _submit_dispatch(inputs: SignupEnrichmentInputs) -> None:
    if not _dispatch_slots.acquire(blocking=False):
        logger.warning(
            "signup_enrichment_dispatch_dropped", organization_id=inputs.organization_id, reason="dispatch_backlog_full"
        )
        return
    try:
        _dispatch_executor.submit(_dispatch_and_release, inputs)
    except Exception as e:
        _dispatch_slots.release()
        capture_exception(e)


def _dispatch_and_release(inputs: SignupEnrichmentInputs) -> None:
    try:
        _dispatch(inputs)
    finally:
        _dispatch_slots.release()


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
                # Rides the general-purpose fleet by default; the SIGNUP_ENRICHMENT_TASK_QUEUE env flips
                # this unauthenticated signup work onto a dedicated, bounded queue once a worker consumes it.
                task_queue=settings.SIGNUP_ENRICHMENT_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            )
        )
    except WorkflowAlreadyStartedError:
        # A re-signup race hits the still-running workflow id; expected, not an error.
        logger.info("signup_enrichment_dispatch_skipped", organization_id=inputs.organization_id)
    except RPCError as e:
        # A transient RPC issue must not surface to signup.
        logger.info("signup_enrichment_dispatch_skipped", organization_id=inputs.organization_id, error=str(e))
    except Exception as e:
        capture_exception(e)
