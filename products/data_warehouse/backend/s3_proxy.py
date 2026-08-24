"""Scoped egress-proxy bypass for the warehouse's own S3 traffic.

Where HTTP_PROXY/HTTPS_PROXY point at an egress proxy, every S3 request becomes a CONNECT tunnel:
two tracked connections on the proxy host (client side and server side) instead of one, each held in
the kernel's connection table for a couple of minutes after close. delta-rs speaks HTTP/1.1 only, so
there is no multiplexing to amortize them either, and request concurrency maps 1:1 onto connections.
A busy warehouse can therefore exhaust connection tracking on hosts it doesn't even run on. Where the
network can already reach S3 directly, that hop buys nothing.

The bypass is deliberately scoped to *this bucket's hostname*, not carved out of the process-wide
NO_PROXY. Egress to customer-controlled destinations (source APIs, customer databases, and a
customer-configured source that happens to point at S3) has to keep going through the proxy.

That scoping is why virtual-hosted addressing is forced: delta-rs addresses S3 path-style by default
(``s3.<region>.amazonaws.com/<bucket>``), which leaves the bucket out of the hostname, so no
host-based rule can distinguish our traffic from anyone else's. Virtual-hosted addressing
(``<bucket>.s3.<region>.amazonaws.com``) puts it back in.

These options reach deltalite too, without it needing to know about any of this: the write path hands
it the same dict, and ``DeltaLiteTable.open`` passes it to ``DeltaTableBuilder::with_storage_options``.

The two clients need different mechanisms:

- delta-rs/object_store has no per-client "ignore the proxy" switch, but reqwest stops consulting
  the environment as soon as a proxy is set explicitly (``ClientBuilder::proxy`` clears
  ``auto_sys_proxy``). So we hand it the same proxy the environment would have given it, plus an
  exclusion for our bucket host.
- botocore takes ``proxies={}`` per client, which overrides the environment directly. Those clients
  only ever address this bucket, so no host-level exclusion is needed.

Every failure mode here is fail-safe: unknown region, missing bucket, absent proxy env or a
hostname that doesn't match what the client actually dials all leave the traffic on the proxy,
exactly as it is today.
"""

import os
import time
from functools import lru_cache
from urllib.parse import urlparse

from django.conf import settings

import posthoganalytics

from posthog.utils import get_instance_region, get_machine_id

# Read at call time rather than reconstructed: the URL can carry per-process auth that whatever
# injected it has already expanded.
_PROXY_ENV_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
_NO_PROXY_ENV_VARS = ("NO_PROXY", "no_proxy")

WAREHOUSE_S3_PROXY_BYPASS_FLAG = "data-warehouse-s3-proxy-bypass"

# Evaluated per process, not per team: which route a pod's S3 packets take is a property of where the
# pod runs. The flag is keyed on the machine id so a percentage rollout ramps whole pods at a time,
# which is also what makes a canary meaningful, because half a pod's requests taking each route would
# tell us nothing. Re-read on this interval so the flag stays a live kill switch: storage options are
# rebuilt constantly, but warehouse activities can run for hours, so caching for the process lifetime
# would mean a flip only lands on the next restart.
_FLAG_CACHE_SECONDS = 60


def _proxy_url() -> str | None:
    for var in _PROXY_ENV_VARS:
        value = os.environ.get(var)
        if value:
            return value
    return None


def _no_proxy() -> str | None:
    for var in _NO_PROXY_ENV_VARS:
        value = os.environ.get(var)
        if value:
            return value
    return None


def warehouse_bucket_host() -> str | None:
    """Virtual-hosted hostname for the warehouse bucket, or None when it can't be determined.

    Derived from BUCKET_URL rather than DATAWAREHOUSE_BUCKET so it always names the bucket the Delta
    tables actually live in.
    """
    bucket = urlparse(settings.BUCKET_URL).netloc
    region = settings.DATA_WAREHOUSE_S3_REGION
    if not bucket or not region:
        return None
    return f"{bucket}.s3.{region}.amazonaws.com"


@lru_cache(maxsize=4)
def _flag_enabled(_interval: int) -> bool:
    """Evaluate the rollout flag, keyed on a time bucket so the cache expires on its own.

    Any evaluation failure returns False (fail closed, as in ``is_deltalite_write_enabled``): a flags
    -service blip leaves traffic on the proxy rather than silently rerouting it.
    """
    try:
        return bool(
            posthoganalytics.feature_enabled(
                WAREHOUSE_S3_PROXY_BYPASS_FLAG,
                get_machine_id(),
                # Surfaced so release conditions can scope the flag to the warehouse workers in a
                # given cloud region, rather than every pod that shares this project token (web,
                # celery, and self-hosted installs all evaluate the same flag). Both values are the
                # ones posthog/apps.py already stamps onto super_properties.
                person_properties={
                    "region": get_instance_region() or "",
                    "service": settings.OTEL_SERVICE_NAME or "",
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception:
        return False


def _bypass_enabled() -> bool:
    # Local dev and tests talk to MinIO/SeaweedFS over an explicit endpoint with no proxy in front.
    if settings.USE_LOCAL_SETUP:
        return False
    return _flag_enabled(int(time.monotonic() // _FLAG_CACHE_SECONDS))


def delta_proxy_storage_options() -> dict[str, str]:
    """delta-rs storage options that keep this bucket's traffic off the egress proxy.

    Empty when the bypass is off or anything it depends on is missing, so callers can merge it
    unconditionally.
    """
    if not _bypass_enabled():
        return {}

    proxy_url = _proxy_url()
    host = warehouse_bucket_host()
    if not proxy_url or not host:
        return {}

    # Setting proxy_url explicitly stops reqwest consulting the environment, which drops the
    # environment's own NO_PROXY along with its proxy. Fold that list back in so hosts the cluster
    # already exempts (IMDS/link-local, in-cluster services, VPC endpoints) keep going direct exactly
    # as they do today, rather than being forced onto the proxy. NoProxy::from_string parses a
    # comma-separated list, CIDRs included.
    excludes = ",".join(filter(None, [host, _no_proxy()]))

    return {
        "proxy_url": proxy_url,
        "proxy_excludes": excludes,
        # Two spellings of the same thing, because two libraries read these options. deltalake-aws
        # parses AWS_S3_ADDRESSING_STYLE; object_store's own S3 builder only knows
        # virtual_hosted_style_request. Which one applies depends on whether the AWS storage handler
        # is registered, and deltalite (rust/deltalite, which passes this dict straight to
        # DeltaTableBuilder) links its own delta-rs build. Setting both means the bucket ends up in
        # the hostname either way; they agree, so neither can contradict the other.
        "AWS_S3_ADDRESSING_STYLE": "virtual",
        "virtual_hosted_style_request": "true",
    }


def boto_proxy_config_kwargs(*, endpoint_url: str | None = None) -> dict[str, object]:
    """botocore config overrides that keep the warehouse S3 clients off the egress proxy.

    Empty when the bypass is off, so callers can merge it unconditionally.

    Gated on the absence of a caller-supplied endpoint_url. Without one the client can only reach
    ``*.s3.<region>.amazonaws.com`` (bucket names can't escape the amazonaws.com zone), so dropping
    the proxy leaves nothing for its private-IP block to catch. An endpoint_url puts the hostname
    under the caller's control (a customer S3-compatible source could point at a private address), so
    the bypass is withheld and that traffic keeps going through the proxy.
    """
    if not _bypass_enabled() or endpoint_url:
        return {}
    return {"proxies": {}}
