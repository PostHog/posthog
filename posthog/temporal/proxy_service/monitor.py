import ssl
import json
import uuid
import socket
import typing as t
import asyncio
import datetime as dt
import ipaddress
from dataclasses import dataclass

import grpc.aio
import requests
import dns.resolver
import temporalio.common
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.exceptions_capture import capture_exception
from posthog.models import ProxyRecord
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.logger import get_logger
from posthog.temporal.proxy_service.cloudflare import (
    CloudflareAPIError,
    CustomHostnameSSLStatus,
    get_custom_hostname_by_domain,
)
from posthog.temporal.proxy_service.common import (
    CaptureEventInputs,
    NonRetriableException,
    RecordDeletedException,
    UpdateProxyRecordInputs,
    activity_capture_event,
    activity_update_proxy_record,
    get_grpc_client,
    get_record,
    is_cloudflare_proxy,
)
from posthog.temporal.proxy_service.proto import CertificateState_READY, StatusRequest

LOGGER = get_logger(__name__)

# Timeout (seconds) for every network call in the live-proxy probe - the POST and the raw-socket
# cert fetch. The domain is attacker-controllable, so an unbounded call lets a malicious domain
# hang the activity until Temporal's start_to_close_timeout. 5.0 (vs the diagnostics probe's 3.0 in
# proxy_record_diagnostics.py) leaves headroom under this activity's 10s start_to_close budget,
# where a single on-demand diagnostics run instead shares its tighter budget across several checks.
PROXY_LIVE_CHECK_TIMEOUT_S = 5.0


@dataclass
class MonitorManagedProxyInputs:
    organization_id: uuid.UUID
    proxy_record_id: uuid.UUID

    @property
    def properties_to_log(self) -> dict[str, t.Any]:
        return {"organization_id": self.organization_id, "proxy_record_id": self.proxy_record_id}


@dataclass
class CheckActivityOutput:
    errors: list[str]
    warnings: list[str]


@dataclass
class CheckActivityInput:
    proxy_record_id: uuid.UUID

    @property
    def properties_to_log(self) -> dict[str, t.Any]:
        return {
            "proxy_record_id": self.proxy_record_id,
        }


@activity.defn
async def check_dns(inputs: CheckActivityInput) -> CheckActivityOutput:
    """Activity that does a DNS lookup for the target subdomain and checks it has a CNAME
    record matching the expected value.
    """
    proxy_record = await get_record(inputs.proxy_record_id)
    if not proxy_record:
        raise RecordDeletedException("proxy record no longer exists")

    bind_contextvars(organization_id=proxy_record.organization_id)
    logger = LOGGER.bind()

    logger.info(
        "Looking up DNS record for %s",
        proxy_record.domain,
    )

    try:
        cnames = dns.resolver.query(proxy_record.domain, "CNAME")
        value = cnames[0].target.canonicalize().to_text()
        if cnames[0].target == dns.name.from_text(proxy_record.target_cname):
            return CheckActivityOutput(
                errors=[],
                warnings=[],
            )
        else:
            return CheckActivityOutput(
                errors=[],
                warnings=[
                    f"Found value: {value} for {proxy_record.domain} DNS record, expected {proxy_record.target_cname}"
                ],
            )
    except dns.resolver.NoAnswer:
        # NoAnswer is not the same as NXDOMAIN
        # It means there is a record set, but it's not a CNAME record
        # A likely reason for this is that they have set Cloudflare proxying on.
        # Check for this explicitly to create a nice message for the user.
        arecords = dns.resolver.query(proxy_record.domain, "A")
        if len(arecords) == 0:
            return CheckActivityOutput(
                errors=["No CNAME or A record DNS records found"],
                warnings=[],
            )

        ip = arecords[0].to_text()

        # this is rare enough and fast enough that it's probably fine
        # but maybe we want to cache this and/or do it async
        cloudflare_ips = requests.get("https://www.cloudflare.com/ips-v4").text.split("\n")
        is_cloudflare = any(ipaddress.ip_address(ip) in ipaddress.ip_network(cidr) for cidr in cloudflare_ips)
        if is_cloudflare:
            # the customer has set cloudflare proxying on
            return CheckActivityOutput(
                errors=[],
                warnings=["The DNS record has Cloudflare proxying enabled - certificate renewal will fail."],
            )

        return CheckActivityOutput(
            errors=["DNS records not found"],
            warnings=[],
        )
    except (dns.resolver.NXDOMAIN, dns.resolver.Timeout, ApplicationError):
        return CheckActivityOutput(
            errors=["Domain name not found"],
            warnings=[],
        )


@activity.defn
async def check_certificate_status(inputs: CheckActivityInput) -> CheckActivityOutput:
    """Activity that checks the certificate status for the proxy"""
    proxy_record = await get_record(inputs.proxy_record_id)
    if not proxy_record:
        raise RecordDeletedException("proxy record no longer exists")

    bind_contextvars(organization_id=proxy_record.organization_id)
    logger = LOGGER.bind()
    logger.info(
        "Checking certificate status for proxy %s (domain %s)",
        proxy_record.id,
        proxy_record.domain,
    )

    # Branch based on how the proxy was created (detected from target_cname),
    # not the global flag, since legacy proxies still need legacy monitoring
    if is_cloudflare_proxy(proxy_record):
        return await _check_cloudflare_certificate_status(proxy_record, logger)
    else:
        return await _check_legacy_certificate_status(proxy_record, logger)


async def _check_cloudflare_certificate_status(proxy_record, logger) -> CheckActivityOutput:
    """Check certificate status via Cloudflare API."""
    try:
        hostname_info = await asyncio.to_thread(get_custom_hostname_by_domain, proxy_record.domain)

        if hostname_info is None:
            return CheckActivityOutput(
                errors=["Custom Hostname not found in Cloudflare"],
                warnings=[],
            )

        if hostname_info.ssl.status != CustomHostnameSSLStatus.ACTIVE:
            return CheckActivityOutput(
                errors=[],
                warnings=[f"TLS Certificate is not active, status: {hostname_info.ssl.status.value}"],
            )

        if hostname_info.ssl.validation_errors:
            error_messages = [err.get("message", "Unknown error") for err in hostname_info.ssl.validation_errors]
            return CheckActivityOutput(
                errors=[],
                warnings=[f"Certificate validation issues: {', '.join(error_messages)}"],
            )

        return CheckActivityOutput(
            errors=[],
            warnings=[],
        )

    except CloudflareAPIError as e:
        raise NonRetriableException(f"Cloudflare API error: {e}") from e


async def _check_legacy_certificate_status(proxy_record, logger) -> CheckActivityOutput:
    """Check certificate status via legacy gRPC proxy provisioner."""
    client = await get_grpc_client()

    try:
        response = await client.Status(
            StatusRequest(
                uuid=str(proxy_record.id),
                domain=proxy_record.domain,
            )
        )

        if response.certificate_status != CertificateState_READY:
            return CheckActivityOutput(
                errors=[],
                warnings=["TLS Certificate is not ready"],
            )

        if response.renewal_time.ToDatetime() < dt.datetime.now() - dt.timedelta(minutes=10):
            return CheckActivityOutput(
                errors=[],
                warnings=["DNS Certificate is not renewing as expected"],
            )

        # if certificate renewal is working it should never allow the cert to come within
        # 3 weeks of expiration (it renews at 4 weeks)
        if response.not_after.ToDatetime() < dt.datetime.now() + dt.timedelta(days=21):
            return CheckActivityOutput(
                errors=[],
                warnings=["DNS Certificate is expiring soon but is unable to be renewed"],
            )

        return CheckActivityOutput(
            errors=[],
            warnings=[],
        )

    except grpc.aio.AioRpcError as e:
        if e.code() == grpc.StatusCode.INVALID_ARGUMENT:
            raise NonRetriableException("invalid argument") from e
        if e.code() == grpc.StatusCode.NOT_FOUND:
            raise NonRetriableException("not found") from e
        raise


@activity.defn
async def check_proxy_is_live(inputs: CheckActivityInput) -> CheckActivityOutput:
    """Activity that checks the certificate status for the proxy"""
    proxy_record = await get_record(inputs.proxy_record_id)
    if not proxy_record:
        raise RecordDeletedException("proxy record no longer exists")

    bind_contextvars(organization_id=proxy_record.organization_id)
    logger = LOGGER.bind()
    logger.info(
        "Checking proxy is live for proxy %s (domain %s)",
        proxy_record.id,
        proxy_record.domain,
    )

    # send dummy event to check the proxy is working
    try:
        # allow_redirects=False is a security boundary: the domain is attacker-controllable
        # (an org admin sets it, and controls its DNS), so following redirects would let them
        # point us at internal targets (ClickHouse's HTTP interface, cloud metadata, management
        # APIs) - an SSRF. A working proxy answers /i/v0/e/ with a 2xx directly. Same protection
        # as the on-demand diagnostics probe in posthog/api/proxy_record_diagnostics.py
        # (_check_live_event).
        response = requests.post(
            f"https://{proxy_record.domain}/i/v0/e/",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"event": "test", "api_key": "test", "distinct_id": "test"}),
            timeout=PROXY_LIVE_CHECK_TIMEOUT_S,
            allow_redirects=False,
        )

        # Since we don't follow redirects, treat a 3xx as a failed check rather than a live proxy:
        # a working proxy answers /i/v0/e/ with a direct 2xx, and a redirect is exactly the response
        # the allow_redirects=False guard above refuses to chase. raise_for_status only rejects
        # 4xx/5xx, so 3xx would otherwise slip through and mark the record VALID.
        if 300 <= response.status_code < 400:
            return CheckActivityOutput(
                errors=[f"Proxy returned a redirect ({response.status_code}); expected a direct 2xx response"],
                warnings=[],
            )

        response.raise_for_status()

        # fetch the cert info to see how far away the expiry is - if less than 2 weeks we have a problem.
        # create_connection carries PROXY_LIVE_CHECK_TIMEOUT_S into the connect and the TLS handshake so
        # an attacker-controlled domain can't stall this raw socket the way it could the POST above -
        # same guard, same reason. Mirrors _check_cert_expiry in proxy_record_diagnostics.py.
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        with socket.create_connection((proxy_record.domain, 443), timeout=PROXY_LIVE_CHECK_TIMEOUT_S) as sock:
            with ctx.wrap_socket(sock, server_hostname=proxy_record.domain) as s:
                cert = s.getpeercert()
        if cert is None:
            # How can cert be none if we sent an event over https?
            raise Exception("Certificate not found while monitoring proxy endpoint (but we sent an event successfully)")
        assert isinstance(cert["notAfter"], str)
        expires_at = dt.datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z")
        if expires_at - dt.datetime.now(dt.UTC).replace(tzinfo=None) < dt.timedelta(days=14):
            return CheckActivityOutput(
                errors=["Live proxy certificate is expiring soon"],
                warnings=[],
            )
    except requests.exceptions.Timeout:
        return CheckActivityOutput(
            errors=["Proxy did not respond within the timeout"],
            warnings=[],
        )
    except requests.exceptions.SSLError:
        return CheckActivityOutput(
            errors=["Failed to connect to proxy: invalid SSL certificate"],
            warnings=[],
        )
    except requests.exceptions.ConnectionError:
        return CheckActivityOutput(
            errors=["Failed to connect to proxy"],
            warnings=[],
        )
    except requests.exceptions.HTTPError as e:
        return CheckActivityOutput(
            errors=[f"Failed to send event to proxy, expected 200 but got {e.response.status_code}"],
            warnings=[],
        )
    except requests.exceptions.RequestException:
        # Any other POST-phase requests failure (malformed response, bad URL, etc). Caught before the
        # stdlib handler below so a POST error isn't mislabelled as a cert-fetch failure - requests
        # exceptions subclass OSError. Mirrors the sibling's broad RequestException handling.
        return CheckActivityOutput(
            errors=["Failed to send event to proxy"],
            warnings=[],
        )
    except (TimeoutError, ssl.SSLError, OSError) as e:
        # Raw-socket cert fetch failed (timeout, refused connection, TLS error). requests exceptions
        # are handled above; this catches the stdlib socket/ssl errors the cert probe can raise.
        return CheckActivityOutput(
            errors=[f"Failed to fetch proxy certificate: {e.__class__.__name__}"],
            warnings=[],
        )

    return CheckActivityOutput(
        errors=[],
        warnings=[],
    )


@dataclass
class CleanupMonitorJobInputs:
    organization_id: uuid.UUID
    proxy_record_id: uuid.UUID

    @property
    def properties_to_log(self) -> dict[str, t.Any]:
        return {
            "organization_id": self.organization_id,
            "proxy_record_id": self.proxy_record_id,
        }


@activity.defn
async def cleanup_monitor_job(inputs: CleanupMonitorJobInputs):
    from posthog.temporal.common.schedule import a_delete_schedule, a_schedule_exists

    bind_contextvars(organization_id=inputs.organization_id)
    logger = LOGGER.bind()
    logger.info(
        "Cleaning up monitoring job for proxy %s",
        inputs.proxy_record_id,
    )

    temporal = await async_connect()
    schedule_id = f"monitor-proxy-{inputs.proxy_record_id}"

    # Check if schedule exists before trying to delete
    if await a_schedule_exists(temporal, schedule_id):
        await a_delete_schedule(temporal, schedule_id)
        logger.info("Successfully deleted monitoring schedule for proxy %s", inputs.proxy_record_id)
    else:
        logger.info("No monitoring schedule found for proxy %s", inputs.proxy_record_id)


@workflow.defn(name="monitor-proxy")
class MonitorManagedProxyWorkflow(PostHogWorkflow):
    """A Temporal Workflow to create a Managed reverse Proxy."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> MonitorManagedProxyInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return MonitorManagedProxyInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: MonitorManagedProxyInputs) -> None:
        """Workflow implementation to create a Managed reverse Proxy."""
        bind_contextvars(organization_id=inputs.organization_id)
        logger = LOGGER.bind()
        logger.info(
            "Running monitor-proxy workflow for proxy %s",
            inputs.proxy_record_id,
        )

        errors = []
        warnings = []

        try:
            check_dns_response = await temporalio.workflow.execute_activity(
                check_dns,
                CheckActivityInput(proxy_record_id=inputs.proxy_record_id),
                schedule_to_close_timeout=dt.timedelta(minutes=1),
                start_to_close_timeout=dt.timedelta(seconds=10),
                retry_policy=temporalio.common.RetryPolicy(
                    backoff_coefficient=1.1,
                    initial_interval=dt.timedelta(seconds=3),
                    maximum_interval=dt.timedelta(seconds=300),
                    maximum_attempts=2,
                    non_retryable_error_types=["NonRetriableException", "RecordDeletedException"],
                ),
            )
            errors += check_dns_response.errors
            warnings += check_dns_response.warnings

            check_proxy_response = await temporalio.workflow.execute_activity(
                check_proxy_is_live,
                CheckActivityInput(proxy_record_id=inputs.proxy_record_id),
                schedule_to_close_timeout=dt.timedelta(minutes=1),
                start_to_close_timeout=dt.timedelta(seconds=10),
                retry_policy=temporalio.common.RetryPolicy(
                    backoff_coefficient=1.1,
                    initial_interval=dt.timedelta(seconds=3),
                    maximum_interval=dt.timedelta(seconds=300),
                    maximum_attempts=2,
                    non_retryable_error_types=["NonRetriableException", "RecordDeletedException"],
                ),
            )
            errors += check_proxy_response.errors
            warnings += check_proxy_response.warnings

            check_certificate_response = await temporalio.workflow.execute_activity(
                check_certificate_status,
                CheckActivityInput(proxy_record_id=inputs.proxy_record_id),
                schedule_to_close_timeout=dt.timedelta(minutes=1),
                start_to_close_timeout=dt.timedelta(seconds=10),
                retry_policy=temporalio.common.RetryPolicy(
                    backoff_coefficient=1.1,
                    initial_interval=dt.timedelta(seconds=3),
                    maximum_interval=dt.timedelta(seconds=300),
                    maximum_attempts=2,
                    non_retryable_error_types=["NonRetriableException", "RecordDeletedException"],
                ),
            )
            errors += check_certificate_response.errors
            warnings += check_certificate_response.warnings

            await temporalio.workflow.execute_activity(
                activity_capture_event,
                CaptureEventInputs(
                    proxy_record_id=inputs.proxy_record_id,
                    organization_id=inputs.organization_id,
                    event_type="monitor-workflow-run",
                    properties={
                        "error_count": len(errors),
                        "warning_count": len(warnings),
                        "error_details": errors,
                        "warning_details": warnings,
                    },
                ),
                schedule_to_close_timeout=dt.timedelta(minutes=1),
                start_to_close_timeout=dt.timedelta(seconds=10),
                retry_policy=temporalio.common.RetryPolicy(
                    backoff_coefficient=1.1,
                    initial_interval=dt.timedelta(seconds=3),
                    maximum_interval=dt.timedelta(seconds=300),
                    maximum_attempts=2,
                    non_retryable_error_types=["NonRetriableException", "RecordDeletedException"],
                ),
            )

            if len(errors) == 0 and len(warnings) == 0:
                await temporalio.workflow.execute_activity(
                    activity_update_proxy_record,
                    UpdateProxyRecordInputs(
                        organization_id=inputs.organization_id,
                        proxy_record_id=inputs.proxy_record_id,
                        status=ProxyRecord.Status.VALID,
                        message="",
                    ),
                    start_to_close_timeout=dt.timedelta(seconds=60),
                    retry_policy=temporalio.common.RetryPolicy(
                        maximum_attempts=10,
                        non_retryable_error_types=["NonRetriableException", "RecordDeletedException"],
                    ),
                )
                return

            warning_messages = "\n\nWarnings:\n- " + "\n- ".join(warnings) if warnings else ""
            error_messages = "\n\nErrors:\n- " + "\n- ".join(errors) if errors else ""

            message = f"""
Issues have been detected with the proxy
{error_messages}{warning_messages}
"""
            if len(errors) > 0:
                await temporalio.workflow.execute_activity(
                    activity_update_proxy_record,
                    UpdateProxyRecordInputs(
                        organization_id=inputs.organization_id,
                        proxy_record_id=inputs.proxy_record_id,
                        status=ProxyRecord.Status.ERRORING,
                        message=message,
                    ),
                    start_to_close_timeout=dt.timedelta(seconds=60),
                    retry_policy=temporalio.common.RetryPolicy(
                        maximum_attempts=10,
                        non_retryable_error_types=["NonRetriableException", "RecordDeletedException"],
                    ),
                )
                return

            await temporalio.workflow.execute_activity(
                activity_update_proxy_record,
                UpdateProxyRecordInputs(
                    organization_id=inputs.organization_id,
                    proxy_record_id=inputs.proxy_record_id,
                    status=ProxyRecord.Status.WARNING,
                    message=message,
                ),
                start_to_close_timeout=dt.timedelta(seconds=60),
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=10,
                    non_retryable_error_types=["NonRetriableException", "RecordDeletedException"],
                ),
            )
        except ActivityError as e:
            if (
                hasattr(e, "cause")
                and e.cause
                and hasattr(e.cause, "type")
                and e.cause.type != "RecordDeletedException"
            ):
                raise

            # cleanup the monitor schedule if the record's been deleted
            await temporalio.workflow.execute_activity(
                cleanup_monitor_job,
                CleanupMonitorJobInputs(
                    organization_id=inputs.organization_id,
                    proxy_record_id=inputs.proxy_record_id,
                ),
                start_to_close_timeout=dt.timedelta(seconds=60),
                retry_policy=temporalio.common.RetryPolicy(
                    maximum_attempts=10,
                    non_retryable_error_types=["NonRetriableException"],
                ),
            )
        except Exception as e:
            capture_exception(e, {"organization_id": inputs.organization_id, "proxy_record_id": inputs.proxy_record_id})
            raise
