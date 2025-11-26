import asyncio

from django.conf import settings

import httpx
import dagster
from dagster_aws.s3 import S3Resource

from posthog.clickhouse.client import query_with_columns
from posthog.clickhouse.cluster import ClickhouseCluster


async def download_google_favicon_async(domain: str, client: httpx.AsyncClient):
    url = f"https://www.google.com/s2/favicons?sz=32&domain={domain}"
    try:
        resp = await client.get(url, timeout=10)
        if resp.status_code == 200 and resp.content:
            return domain, resp.content, resp.headers.get("content-type")
        return domain, None, None
    except Exception:
        return domain, None, None


async def download_ddg_favicon_async(domain: str, client: httpx.AsyncClient):
    url = f"https://icons.duckduckgo.com/ip3/{domain}.ico"
    try:
        resp = await client.get(url, timeout=10)
        if resp.status_code == 200 and resp.content:
            content_type = resp.headers.get("content-type")
            return domain, resp.content, content_type
        return domain, None, None
    except Exception:
        return domain, None, None


async def batch_download(domains, concurrency=20):
    async with httpx.AsyncClient() as client:
        sem = asyncio.Semaphore(concurrency)

        async def worker(domain):
            async with sem:
                icon = await download_google_favicon_async(f"https://{domain}", client)

                if icon is None:
                    icon = await download_ddg_favicon_async(domain, client)

                return icon

        return await asyncio.gather(*(worker(domain) for domain in domains))


def upload_if_missing(s3_client, bucket, key, data, content_type):
    # Ignore uploading if the favicon already exists in our cache
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return key
    except s3_client.exceptions.ClientError:
        pass

    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
    )
    return key


@dagster.asset
def cache_favicons(s3: S3Resource, cluster: dagster.ResourceParam[ClickhouseCluster]):
    top_referrer_query = """
        SELECT cutToFirstSignificantSubdomainWithWWW(JSONExtractString(properties, '$referrer')) AS referrer
        FROM events
        WHERE event = '$pageview'
            AND timestamp >= now() - interval 90 day
            AND referrer is not null and referrer != ''
        GROUP BY referrer
        HAVING count(*) > 1000
        LIMIT 5000
    """

    result, _ = query_with_columns(top_referrer_query)
    domains = [r[0] for r in result]

    items = asyncio.run(batch_download(domains, concurrency=25))

    s3_client = s3.get_client()

    uploaded = []
    for domain, data, content_type in items:
        if data is None:
            continue
        key = f"/favicons/{domain}.png"
        upload_if_missing(
            s3_client,
            settings.DAGSTER_FAVICONS_S3_BUCKET,
            key,
            data,
            content_type,
        )
        uploaded.append(key)

    return uploaded
