from urllib.parse import urlparse

from django.db import migrations
from django.utils import timezone

import tldextract

# The same settings as posthog.api.oauth.cimd._DOMAIN_PARTS, written out so this migration keeps
# its meaning if that module changes.
_DOMAIN_PARTS = tldextract.TLDExtract(suffix_list_urls=(), include_psl_private_domains=True)
_REASON = "Already a provisioning partner before reviews existed"
_REFUSED_HOST_REASON = (
    "Already a provisioning partner before reviews existed, on a host that registration now refuses. "
    "Reject it to disable provisioning, or accept it to keep it."
)


def _registrable_domain(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").rstrip(".").lower()
    except ValueError:
        return ""
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            return ""
    return _DOMAIN_PARTS(host).top_domain_under_public_suffix


def backfill_accepted_reviews(apps, schema_editor):
    """Record every active CIMD partner as reviewed, because it was trusted before reviews existed.

    Only active partners that are not disabled get a row. An accepted row lets a later client on
    the same host skip part of the review, so an admin-blocked partner must not get one. A partner
    whose metadata host registration now refuses gets a row that waits for staff instead, so staff
    can reject it from PostHog Admin. Admin-created partners have no CIMD URL and never go
    through a review.
    """
    # Imported here so that a fresh database, which has no partners to check, never depends on
    # the current shape of this module.
    from posthog.api.oauth.cimd import is_throwaway_host

    OAuthApplication = apps.get_model("posthog", "OAuthApplication")
    CIMDProvisioningReview = apps.get_model("posthog", "CIMDProvisioningReview")

    now = timezone.now()
    partners = OAuthApplication.objects.filter(is_cimd_client=True, is_provisioning_partner=True).exclude(
        provisioning_review__isnull=False
    )
    reviews = []
    for app in partners.iterator():
        config = app._provisioning_config or {}
        if not config.get("active") or config.get("disabled"):
            continue
        if is_throwaway_host(app.client_id):
            reviews.append(
                CIMDProvisioningReview(
                    application_id=app.pk,
                    domain=_registrable_domain(app.client_id),
                    status="needs_human",
                    reason=_REFUSED_HOST_REASON,
                    run_log=[
                        {
                            "at": now.isoformat(),
                            "step": "backfill",
                            "level": "warning",
                            "message": _REFUSED_HOST_REASON,
                        }
                    ],
                )
            )
            continue
        reviews.append(
            CIMDProvisioningReview(
                application_id=app.pk,
                domain=_registrable_domain(app.client_id),
                status="accepted",
                decided_stage="staff",
                reason=_REASON,
                decided_at=now,
                run_log=[
                    {
                        "at": now.isoformat(),
                        "step": "backfill",
                        "level": "info",
                        "message": _REASON,
                    }
                ],
            )
        )
    CIMDProvisioningReview.objects.bulk_create(reviews, ignore_conflicts=True)


class Migration(migrations.Migration):
    dependencies = [("posthog", "1437_cimd_provisioning_review")]

    operations = [
        # Reverse is a no-op: rolling back 1437 drops the table and these rows with it.
        migrations.RunPython(backfill_accepted_reviews, migrations.RunPython.noop),
    ]
