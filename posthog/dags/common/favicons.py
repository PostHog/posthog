"""Shared favicon caching for Dagster assets. Every asset stores favicons in the same bucket under
`favicons/<domain>`, which the static CDN serves at `<JS_URL>/favicons/<domain>`."""

import time
import datetime as dt
from typing import NamedTuple, cast

from django.conf import settings

import httpx
import dagster
from dagster_aws.s3 import S3Resource

from posthog.dataclasses import frozen


def get_last_cached_domains(context: dagster.AssetExecutionContext, asset_key: str) -> set[str]:
    last_mat = context.instance.get_latest_materialization_event(dagster.AssetKey([asset_key]))
    if not last_mat or not last_mat.asset_materialization:
        return set()

    metadata = last_mat.asset_materialization.metadata
    cached_domains_meta = metadata.get("cached_domains")
    if cached_domains_meta and isinstance(cached_domains_meta, dagster.JsonMetadataValue):
        return set(cast(list[str], cached_domains_meta.value))
    return set()


class CacheFaviconsConfig(dagster.Config):
    force_refresh: bool = False


@frozen
class DownloadedFavicon:
    data: bytes
    content_type: str | None
    source_url: str


def download_favicon(
    context: dagster.AssetExecutionContext, domain: str, client: httpx.Client
) -> DownloadedFavicon | None:
    context.log.info(f"Attempting to download favicon for domain '{domain}'")
    urls = [
        f"https://icons.duckduckgo.com/ip3/{domain}.ico",
        f"https://t0.gstatic.com/faviconV2?client=SOCIAL&type=FAVICON&fallback_opts=TYPE,SIZE,URL&url=https://{domain}&size=32",
    ]

    for url in urls:
        try:
            resp = client.get(url, timeout=10)
            if resp.status_code == 200 and resp.content:
                context.log.info(f"Found favicon for {domain} at {url}")
                return DownloadedFavicon(
                    data=resp.content, content_type=resp.headers.get("content-type"), source_url=url
                )
        except Exception:
            context.log.exception(f"Failed to download favicon from: {url}")
            continue

    return None


def upload_if_missing(context: dagster.AssetExecutionContext, s3_client, bucket, key, data, content_type):
    context.log.info(f"Attempting to cache {key}")
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        context.log.info("Favicon already cached, skipping upload.")
        return key
    except s3_client.exceptions.ClientError:
        pass

    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )

    context.log.info("Favicon successfully cached.")
    return key


class FaviconCacheRun(NamedTuple):
    favicons: list[dict]
    cached_domains: set[str]
    skipped_count: int
    failed_domains: set[str]
    out_of_time: bool


def download_and_cache_favicons(
    context: dagster.AssetExecutionContext,
    s3: S3Resource,
    domains: list[str],
    previously_cached: set[str],
    time_budget: dt.timedelta | None = None,
) -> FaviconCacheRun:
    """Download and cache favicons for a list of domains. With a time budget, stops starting new
    downloads once it is spent and reports `out_of_time`."""
    s3_client = s3.get_client()
    bucket = settings.DAGSTER_FAVICONS_S3_BUCKET
    deadline = time.monotonic() + time_budget.total_seconds() if time_budget is not None else None

    favicons: list[dict] = []
    all_cached_domains = previously_cached.copy()
    skipped_count = 0
    failed_domains: set[str] = set()

    with httpx.Client() as client:
        for domain in domains:
            if domain in previously_cached:
                context.log.debug(f"Skipping download for '{domain}' - already cached.")
                skipped_count += 1
                continue

            if deadline is not None and time.monotonic() >= deadline:
                context.log.info("Time budget spent, leaving the remaining domains for the next run.")
                return FaviconCacheRun(favicons, all_cached_domains, skipped_count, failed_domains, True)

            favicon = download_favicon(context, domain, client)
            if favicon is None:
                failed_domains.add(domain)
                continue

            key = f"favicons/{domain}"
            upload_if_missing(context, s3_client, bucket, key, favicon.data, favicon.content_type)
            all_cached_domains.add(domain)
            favicons.append(
                {
                    "domain": domain,
                    "source_url": favicon.source_url,
                    "cached_url": f"s3://{bucket}{key}",
                    "favicon_url": f"/static/favicons/{domain}",
                }
            )

    return FaviconCacheRun(favicons, all_cached_domains, skipped_count, failed_domains, False)
