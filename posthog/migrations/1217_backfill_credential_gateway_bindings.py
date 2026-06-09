from collections import defaultdict

from django.db import migrations

_GATEWAY_SCOPE = "llm_gateway:read"
# Slug of the gateway seeded by 1216; this catch-up binds to it by slug.
_DEFAULT_SLUG = "default"


def backfill_credential_gateway_bindings(apps, schema_editor):
    """Bind pre-existing llm_gateway:read credentials to their team's seeded gateway.

    Runs after 1216, so every canonical team already has its initial gateway. A
    gateway can hold many keys (ForeignKey), so all of a team's eligible credentials
    bind to the one seeded gateway. Idempotent: only rows still unbound are touched;
    new credentials are bound at mint time, so this is a one-time catch-up. Signals
    don't fire — historical models are distinct classes from the ones receivers target.

    Binds only when a single authoritative team is derivable (a singleton scoped_team,
    or a singleton scoped_organization's root team). Anything ambiguous is left unbound
    — a guessed binding silently misattributes billing, whereas an unbound credential
    fails closed and can be bound explicitly later. Writes are grouped by resolved
    gateway and issued as one UPDATE per gateway rather than a save() per row.
    """
    PersonalAPIKey = apps.get_model("posthog", "PersonalAPIKey")
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
        return (
            Team.objects.filter(organization_id=organization_id, parent_team_id__isnull=True)
            .values_list("id", flat=True)
            .first()
        )

    # Personal keys carry the scope directly. Resolve a single authoritative team
    # (singleton scoped_team, else singleton scoped_organization's root team); leave
    # ambiguous keys unbound rather than guessing from mutable session state.
    pak_binds: dict[int, list] = defaultdict(list)
    paks = PersonalAPIKey.objects.filter(scopes__contains=[_GATEWAY_SCOPE], gateway__isnull=True)
    for pak in paks.iterator():
        if pak.scoped_teams and len(pak.scoped_teams) == 1:
            team_id = pak.scoped_teams[0]
        elif pak.scoped_organizations and len(pak.scoped_organizations) == 1:
            team_id = org_root_team_id(pak.scoped_organizations[0])
        else:
            team_id = None
        gateway_id = default_gateway_id(team_id)
        if gateway_id is not None:
            pak_binds[gateway_id].append(pak.pk)
    for gateway_id, ids in pak_binds.items():
        PersonalAPIKey.objects.filter(pk__in=ids).update(gateway_id=gateway_id)

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
    # Non-atomic: the OAuth scope lookup is a regex scan over the access-token table
    # (regex isn't indexable), so keep it out of one long transaction. Safe because the
    # backfill is idempotent — only gateway__isnull rows are touched, so a mid-run
    # failure just re-runs.
    atomic = False

    dependencies = [
        ("posthog", "1216_backfill_default_gateways"),
    ]

    operations = [
        migrations.RunPython(backfill_credential_gateway_bindings, migrations.RunPython.noop),
    ]
