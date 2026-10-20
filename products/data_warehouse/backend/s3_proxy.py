"""Virtual-hosted S3 addressing, and a scoped egress-proxy bypass, for the warehouse's own S3 traffic.

delta-rs/object_store address S3 path-style by default (``<endpoint>/<bucket>``). AWS still accepts
that for buckets created before it deprecated the style in 2020, but plenty of real S3-compatible
stores refuse it outright (Alibaba OSS returns "please use virtual hosted style to access" on it).
Virtual-hosted addressing (``<bucket>.<endpoint>``) works everywhere a bucket is reachable by a real,
DNS-resolvable hostname, which is every non-local deployment: the in-stack MinIO/SeaweedFS of
USE_LOCAL_SETUP is the only backend here addressed by raw host:port instead, and it takes a separate,
explicit-endpoint code path that never reaches this module. So addressing style is forced below
independent of anything else in this file, not only as a side effect of the proxy bypass that follows.

One exception: a bucket name containing a dot stays on path-style (see
_bucket_supports_virtual_hosted_style) - AWS's wildcard TLS cert for its own S3 endpoints doesn't
cover the extra hostname label a dot introduces, so forcing virtual-hosted addressing there breaks
certificate validation instead of fixing anything.

Where HTTP_PROXY/HTTPS_PROXY point at an egress proxy, every S3 request becomes a CONNECT tunnel:
two tracked connections on the proxy host (client side and server side) instead of one, each held in
the kernel's connection table for a couple of minutes after close. delta-rs speaks HTTP/1.1 only, so
there is no multiplexing to amortize them either, and request concurrency maps 1:1 onto connections.
A busy warehouse can therefore exhaust connection tracking on hosts it doesn't even run on. Where the
network can already reach S3 directly, that hop buys nothing.

The bypass is deliberately scoped to *this bucket's hostname*, not carved out of the process-wide
NO_PROXY. Egress to customer-controlled destinations (source APIs, customer databases, and a
customer-configured source that happens to point at S3) has to keep going through the proxy. That
scoping relies on virtual-hosted addressing too: path-style leaves the bucket out of the hostname, so
no host-based rule could distinguish our traffic from anyone else's.

These options reach deltalite too, without it needing to know about any of this: the write path hands
it the same dict, and ``DeltaLiteTable.open`` passes it to ``DeltaTableBuilder::with_storage_options``.

The two clients need different mechanisms:

- delta-rs/object_store has no per-client "ignore the proxy" switch, but reqwest stops consulting
  the environment as soon as a proxy is set explicitly (``ClientBuilder::proxy`` clears
  ``auto_sys_proxy``). So we hand it the same proxy the environment would have given it, plus an
  exclusion for our bucket host.
- botocore takes ``proxies={}`` per client, which overrides the environment directly. Those clients
  only ever address this bucket, so no host-level exclusion is needed.

Every proxy-bypass failure mode is fail-safe: unknown region, missing bucket, absent proxy env or a
hostname that doesn't match what the client actually dials all leave the traffic on the proxy,
exactly as it is today. Addressing style carries no such fallback - it does not depend on any of
those - because leaving it unset is exactly the bug this module now avoids.
"""

import os
from urllib.parse import urlparse

from django.conf import settings

# Read at call time rather than reconstructed: the URL can carry per-process auth that whatever
# injected it has already expanded.
_PROXY_ENV_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")
_NO_PROXY_ENV_VARS = ("NO_PROXY", "no_proxy")


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


def _using_real_bucket() -> bool:
    # Local dev and tests talk to MinIO/SeaweedFS over an explicit endpoint with no proxy in front,
    # and addressed by raw host:port rather than a DNS name a virtual-hosted request could use.
    return not settings.USE_LOCAL_SETUP


def _bucket_supports_virtual_hosted_style() -> bool:
    """False for a bucket name that itself contains a dot.

    AWS's wildcard TLS cert for ``*.s3.<region>.amazonaws.com`` covers exactly one subdomain
    label. A bucket name with a dot in it (a legal, if discouraged, S3 bucket name) produces a
    virtual-hosted hostname with an extra label the cert doesn't cover, so the request fails
    certificate validation - see
    https://docs.aws.amazon.com/AmazonS3/latest/userguide/VirtualHosting.html. Path-style still
    works for those buckets, so they stay on it.
    """
    bucket = urlparse(settings.BUCKET_URL).netloc
    return bool(bucket) and "." not in bucket


def _addressing_style_options() -> dict[str, str]:
    if not _using_real_bucket() or not _bucket_supports_virtual_hosted_style():
        return {}
    return {
        # Two spellings of the same thing, because two libraries read these options. deltalake-aws
        # parses AWS_S3_ADDRESSING_STYLE; object_store's own S3 builder only knows
        # virtual_hosted_style_request. Which one applies depends on whether the AWS storage handler
        # is registered, and deltalite (rust/deltalite, which passes this dict straight to
        # DeltaTableBuilder) links its own delta-rs build. Setting both means the bucket ends up in
        # the hostname either way; they agree, so neither can contradict the other.
        "AWS_S3_ADDRESSING_STYLE": "virtual",
        "virtual_hosted_style_request": "true",
    }


def delta_proxy_storage_options() -> dict[str, str]:
    """delta-rs storage options for the warehouse bucket: forced virtual-hosted addressing (see
    module docstring), plus keeping this bucket's traffic off the egress proxy where one is
    configured.

    Empty when not using a real bucket, so callers can merge it unconditionally.
    """
    options = _addressing_style_options()
    if not _using_real_bucket() or not _bucket_supports_virtual_hosted_style():
        # A dotted bucket name never gets addressed virtual-hosted (see
        # _bucket_supports_virtual_hosted_style), so a host-based proxy exclusion below would name
        # a hostname delta-rs never actually dials and never bypass anything. Stop here instead.
        return options

    proxy_url = _proxy_url()
    host = warehouse_bucket_host()
    if not proxy_url or not host:
        return options

    # Setting proxy_url explicitly stops reqwest consulting the environment, which drops the
    # environment's own NO_PROXY along with its proxy. Fold that list back in so hosts the cluster
    # already exempts (IMDS/link-local, in-cluster services, VPC endpoints) keep going direct exactly
    # as they do today, rather than being forced onto the proxy. NoProxy::from_string parses a
    # comma-separated list, CIDRs included.
    excludes = ",".join(filter(None, [host, _no_proxy()]))

    return {
        **options,
        "proxy_url": proxy_url,
        "proxy_excludes": excludes,
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
    if not _using_real_bucket() or endpoint_url:
        return {}
    return {"proxies": {}}
