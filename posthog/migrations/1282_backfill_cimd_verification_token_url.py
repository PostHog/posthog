from urllib.parse import urlparse

from django.db import migrations


def _normalize_cimd_url(url: str) -> str:
    """Frozen copy of posthog.models.oauth.normalize_cimd_url.

    Duplicated rather than imported: a migration module is loaded while Django
    builds the migration graph, so importing app code here runs it far too early.
    Migrations also have to stay pinned to the behavior they shipped with.
    """
    parsed = urlparse(url.strip())
    try:
        port = parsed.port
    except ValueError:
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
    host = (parsed.hostname or "").lower()
    if port and port != 443:
        host = f"{host}:{port}"
    return f"{parsed.scheme.lower()}://{host}{parsed.path.rstrip('/')}"


def backfill_cimd_url(apps, schema_editor):
    """Bind existing tokens to the document they already verified.

    Without this, every already-verified partner silently drops to the unverified
    rate-limit tier on their next metadata refresh.

    Only unambiguous cases are backfilled: an organization with exactly one token
    and exactly one verified CIMD app can only have used that token for that app.
    Anything else is left null, which fails closed — those partners reissue a
    token against an explicit URL.
    """
    CIMDVerificationToken = apps.get_model("posthog", "CIMDVerificationToken")
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")

    verified_apps = (
        OAuthApplication.objects.filter(
            is_cimd_client=True,
            organization_id__isnull=False,
            cimd_metadata_url__isnull=False,
        )
        .exclude(cimd_metadata_url="")
        .values_list("organization_id", "cimd_metadata_url")
        .iterator()
    )

    urls_by_org: dict[str, list[str]] = {}
    for org_id, url in verified_apps:
        urls_by_org.setdefault(str(org_id), []).append(url)

    to_update = []
    for org_id, urls in urls_by_org.items():
        if len(urls) != 1:
            continue
        tokens = list(CIMDVerificationToken.objects.filter(organization_id=org_id)[:2])
        if len(tokens) != 1:
            continue
        tokens[0].cimd_url = _normalize_cimd_url(urls[0])
        to_update.append(tokens[0])

    CIMDVerificationToken.objects.bulk_update(to_update, ["cimd_url"], batch_size=1000)


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1281_cimdverificationtoken_cimd_url"),
    ]

    operations = [
        migrations.RunPython(backfill_cimd_url, migrations.RunPython.noop, elidable=True),
    ]
