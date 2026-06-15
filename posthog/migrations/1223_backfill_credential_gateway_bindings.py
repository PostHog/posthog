from collections import defaultdict

from django.db import migrations

# Slug of the gateway seeded by 1216; this catch-up binds to it by slug.
_DEFAULT_SLUG = "default"


def backfill_credential_gateway_bindings(apps, schema_editor):
    """One-time catch-up binding pre-existing llm_gateway:read OAuth apps to their gateway.

    Binds only when the org has one root team; ambiguous (multi-root) is left unbound
    rather than misattributing billing. Project secret keys aren't backfilled (team-
    scoped, minted for other purposes). Idempotent (only unbound rows), one bulk UPDATE
    per gateway; signals don't fire on historical models.
    """
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")
    OAuthAccessToken = apps.get_model("posthog", "OAuthAccessToken")
    Team = apps.get_model("posthog", "Team")
    Gateway = apps.get_model("posthog", "Gateway")
    gateways = Gateway._default_manager  # default manager is `all_teams`; no `.objects`

    canonical: dict[int, int] = {}
    seeded_gateway: dict[int, int | None] = {}

    def default_gateway_id(team_id: int | None) -> int | None:
        if not team_id:
            return None
        if team_id not in canonical:
            parent = Team.objects.filter(pk=team_id).values_list("parent_team_id", flat=True).first()
            canonical[team_id] = parent or team_id
        canon = canonical[team_id]
        if canon not in seeded_gateway:
            seeded_gateway[canon] = (
                gateways.filter(team_id=canon, slug=_DEFAULT_SLUG).values_list("id", flat=True).first()
            )
        return seeded_gateway[canon]

    def org_root_team_id(organization_id: int | str | None) -> int | None:
        if not organization_id:
            return None
        # One root team → bind; ambiguous (multi-root org) → unbound. Fetch 2 to detect it.
        roots = list(
            Team.objects.filter(organization_id=organization_id, parent_team_id__isnull=True)
            .order_by("id")
            .values_list("id", flat=True)[:2]
        )
        return roots[0] if len(roots) == 1 else None

    # Scope lives on issued tokens; bind the application to its org's root team.
    app_ids = set(
        OAuthAccessToken.objects.filter(
            scope__iregex=r"(^|\s)llm_gateway:read(\s|$)", application_id__isnull=False
        ).values_list("application_id", flat=True)
    )
    app_binds: dict[int, list] = defaultdict(list)
    apps_qs = OAuthApplication.objects.filter(id__in=app_ids, gateway__isnull=True)
    for application in apps_qs.iterator():
        gateway_id = default_gateway_id(org_root_team_id(application.organization_id))
        if gateway_id is not None:
            app_binds[gateway_id].append(application.pk)
    for gateway_id, ids in app_binds.items():
        OAuthApplication.objects.filter(pk__in=ids).update(gateway_id=gateway_id)


class Migration(migrations.Migration):
    # Atomic: short transaction over a small set, idempotent re-runs. The OAuth scope
    # regex scan is unindexable but a read (ACCESS SHARE, no heavy lock); writes are bulk.
    dependencies = [
        ("posthog", "1222_backfill_default_gateways"),
    ]

    operations = [
        migrations.RunPython(backfill_credential_gateway_bindings, migrations.RunPython.noop),
    ]
