from urllib.parse import urlparse

from django.db import migrations

import structlog

logger = structlog.get_logger(__name__)

# Sentinel a real normalized URL can never equal, so an unparseable input fails the
# equality checks upstream instead of silently matching something.
_UNNORMALIZABLE_URL = "\x00unnormalizable"


def _normalize_cimd_url(url: str) -> str:
    """Frozen copy of posthog.models.oauth.normalize_cimd_url.

    Duplicated rather than imported: a migration module is loaded while Django
    builds the migration graph, so importing app code here runs it far too early.
    Migrations also have to stay pinned to the behavior they shipped with.
    """
    try:
        parsed = urlparse(url.strip())
        port = parsed.port
    except ValueError:
        # Covers both an unparseable port ("h:abc", "h:99999") and a URL urlparse
        # itself rejects ("https://[::1/x.json"). Either way there is nothing to
        # normalize into, so the caller must not treat this as a real URL.
        return _UNNORMALIZABLE_URL
    host = (parsed.hostname or "").lower()
    if port and port != 443:
        host = f"{host}:{port}"
    return f"{parsed.scheme.lower()}://{host}{parsed.path.rstrip('/')}"


def backfill_cimd_url(apps, schema_editor):
    """Bind existing tokens to the document they already verified.

    Without this, every already-verified partner silently drops to the unverified
    rate-limit tier on their next metadata refresh.

    A token binds an organization to whichever CIMD document embeds it, so nothing
    here can rely on organization_id__isnull=False alone: the vulnerability this PR
    fixes is exactly that link being spoofable by copying a token into a document at
    another URL. Every row backfilled here has to be corroborated instead of merely
    plausible, so a candidate is written only when ALL of the following hold:

    - the organization's verified CIMD apps all normalize to one URL (cimd_metadata_url
      is unique, so two apps can only name one document by spelling it differently;
      two genuinely different URLs are ambiguous);
    - that URL normalizes to a real value;
    - the organization has exactly one token that isn't already bound;
    - that token has actually verified something before (last_used_at is set).

    Deliberately not required: that the token predate the app. A CIMD app self-registers
    on its first /authorize, and the admin issues a token and republishes the document
    afterwards, so a token newer than its app is the ordinary sequence rather than a
    suspicious one. Rejecting it skipped live partners while corroborating nothing that
    last_used_at does not already cover.

    Anything else is left null, which fails closed - those partners reissue a token
    against an explicit URL, or bind the existing one from the settings page.
    """
    CIMDVerificationToken = apps.get_model("posthog", "CIMDVerificationToken")
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")

    # Pinned to the alias `migrate` is running on rather than letting the router pick, for the
    # same reasons as 1274: bin/migrate uses `default_direct`, and the router would otherwise
    # send these reads and the bulk_update to `default`, where DISABLE_SERVER_SIDE_CURSORS makes
    # .iterator() buffer the whole result set client-side, the writes commit outside the
    # migration's transaction, and there's no lock_timeout to fail fast under contention.
    db_alias = schema_editor.connection.alias

    verified_apps = (
        OAuthApplication.objects.using(db_alias)
        .filter(
            is_cimd_client=True,
            organization_id__isnull=False,
            cimd_metadata_url__isnull=False,
        )
        .exclude(cimd_metadata_url="")
        .values_list("organization_id", "cimd_metadata_url")
        .iterator()
    )

    # Normalized before grouping, not compared as raw strings: cimd_metadata_url is unique,
    # so two apps can only ever "share" a document by spelling it differently (host case,
    # an explicit :443, a trailing slash). Those are one document, not ambiguity.
    normalized_urls_by_org: dict[str, set[str]] = {}
    for org_id, url in verified_apps:
        normalized_urls_by_org.setdefault(str(org_id), set()).add(_normalize_cimd_url(url))

    skipped_ambiguous_url = 0
    skipped_unnormalizable_url = 0
    candidate_urls_by_org: dict[str, str] = {}
    for org_id, normalized_urls in normalized_urls_by_org.items():
        if _UNNORMALIZABLE_URL in normalized_urls:
            skipped_unnormalizable_url += 1
            continue
        if len(normalized_urls) != 1:
            skipped_ambiguous_url += 1
            continue
        (candidate_urls_by_org[org_id],) = normalized_urls

    tokens_by_org: dict[str, list] = {}
    candidate_tokens = (
        CIMDVerificationToken.objects.using(db_alias)
        .filter(organization_id__in=candidate_urls_by_org.keys(), cimd_url__isnull=True)
        .only("id", "organization_id", "last_used_at")
        .iterator()
    )
    for token in candidate_tokens:
        tokens_by_org.setdefault(str(token.organization_id), []).append(token)

    skipped_no_single_eligible_token = 0
    skipped_token_never_used = 0
    to_update = []
    written = []
    for org_id, normalized_url in candidate_urls_by_org.items():
        tokens = tokens_by_org.get(org_id, [])
        if len(tokens) != 1:
            skipped_no_single_eligible_token += 1
            continue
        token = tokens[0]
        if token.last_used_at is None:
            skipped_token_never_used += 1
            continue
        token.cimd_url = normalized_url
        to_update.append(token)
        written.append({"token_id": str(token.id), "organization_id": org_id, "cimd_url": normalized_url})

    if to_update:
        CIMDVerificationToken.objects.using(db_alias).bulk_update(to_update, ["cimd_url"], batch_size=1000)

    if written:
        logger.warning("cimd_verification_tokens_backfilled", bindings=written)
    logger.warning(
        "cimd_verification_tokens_backfill_skipped",
        ambiguous_url=skipped_ambiguous_url,
        unnormalizable_url=skipped_unnormalizable_url,
        no_single_eligible_token=skipped_no_single_eligible_token,
        token_never_used=skipped_token_never_used,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1295_cimdverificationtoken_cimd_url"),
    ]

    operations = [
        migrations.RunPython(backfill_cimd_url, migrations.RunPython.noop, elidable=True),
    ]
