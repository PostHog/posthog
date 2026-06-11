from collections import defaultdict

from django.db import migrations

# Slug of the gateway seeded by 1216; this catch-up binds to it by slug.
_DEFAULT_SLUG = "default"


def backfill_credential_gateway_bindings(apps, schema_editor):
    """Bind pre-existing llm_gateway:read OAuth applications to their team's seeded gateway.

    Runs after 1216, so every canonical team already has its initial gateway. A
    gateway can hold many keys (ForeignKey), so all of an org's eligible applications
    bind to the one seeded gateway. Idempotent: only rows still unbound are touched;
    new applications are bound at mint time, so this is a one-time catch-up. Signals
    don't fire — historical models are distinct classes from the ones receivers target.

    Binds only when a single authoritative team is derivable (the org's one root team).
    Anything ambiguous is left unbound — a guessed binding silently misattributes
    billing, whereas an unbound credential fails closed and can be bound explicitly
    later. Project secret keys are not backfilled: they're directly team-scoped and were
    minted for other purposes, so auto-binding them to a gateway would misattribute.
    Writes are grouped by resolved gateway and issued as one UPDATE per gateway.
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
        # Bind only when the org has exactly one root team — a multi-project org has no
        # single authoritative gateway, so leave the credential unbound. Fetch two to
        # detect ambiguity without counting the whole set.
        roots = list(
            Team.objects.filter(organization_id=organization_id, parent_team_id__isnull=True)
            .order_by("id")
            .values_list("id", flat=True)[:2]
        )
        return roots[0] if len(roots) == 1 else None

    # OAuth scope lives on issued tokens; the binding is per-application. An app
    # belongs to an organization, so attribute it to the org's root team; an app with
    # no organization has no authoritative team and is left unbound.
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
    # Atomic (the default): only the small set of pre-existing llm_gateway:read
    # credentials is touched, so the transaction is short and re-runs are idempotent
    # (only gateway__isnull rows are bound). The OAuth scope lookup is an unindexable
    # regex scan, but it's a read (ACCESS SHARE snapshot, no heavy lock); the writes
    # are bulk updates on a bounded set.
    dependencies = [
        ("posthog", "1217_backfill_default_gateways"),
    ]

    operations = [
        migrations.RunPython(backfill_credential_gateway_bindings, migrations.RunPython.noop),
    ]
