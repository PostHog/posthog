from django.db import migrations

_GATEWAY_SCOPE = "llm_gateway:read"


def backfill_credential_gateway_bindings(apps, schema_editor):
    """Bind pre-existing llm_gateway:read credentials to their team's default gateway.

    Runs after 1216, so every canonical team already has a default gateway. A
    gateway can hold many keys (ForeignKey), so all of a team's eligible credentials
    bind to the one default. Idempotent: only rows still unbound are touched; new
    credentials are bound at mint time, so this is a one-time catch-up. Signals don't
    fire — historical models are distinct classes from the ones receivers target.
    """
    PersonalAPIKey = apps.get_model("posthog", "PersonalAPIKey")
    OAuthApplication = apps.get_model("posthog", "OAuthApplication")
    OAuthAccessToken = apps.get_model("posthog", "OAuthAccessToken")
    Team = apps.get_model("posthog", "Team")
    Gateway = apps.get_model("posthog", "Gateway")
    gateways = Gateway._default_manager  # default manager is `all_teams`; no `.objects`

    canonical: dict[int, int] = {}
    default_gateway: dict[int, int | None] = {}

    def default_gateway_id(team_id: int | None) -> int | None:
        if not team_id:
            return None
        if team_id not in canonical:
            parent = Team.objects.filter(pk=team_id).values_list("parent_team_id", flat=True).first()
            canonical[team_id] = parent or team_id
        canon = canonical[team_id]
        if canon not in default_gateway:
            default_gateway[canon] = (
                gateways.filter(team_id=canon, is_default=True).values_list("id", flat=True).first()
            )
        return default_gateway[canon]

    # Personal keys carry the scope directly.
    paks = PersonalAPIKey.objects.filter(scopes__contains=[_GATEWAY_SCOPE], gateway__isnull=True).select_related("user")
    for pak in paks.iterator():
        gateway_id = default_gateway_id(pak.user.current_team_id if pak.user_id else None)
        if gateway_id is not None:
            pak.gateway_id = gateway_id
            pak.save(update_fields=["gateway"])

    # OAuth scope lives on issued tokens; the binding is per-application.
    app_ids = set(
        OAuthAccessToken.objects.filter(
            scope__iregex=r"(^|\s)llm_gateway:read(\s|$)", application_id__isnull=False
        ).values_list("application_id", flat=True)
    )
    apps_qs = OAuthApplication.objects.filter(id__in=app_ids, gateway__isnull=True).select_related("user")
    for application in apps_qs.iterator():
        gateway_id = default_gateway_id(application.user.current_team_id if application.user_id else None)
        if gateway_id is not None:
            application.gateway_id = gateway_id
            application.save(update_fields=["gateway"])


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("posthog", "1216_backfill_default_gateways"),
    ]

    operations = [
        migrations.RunPython(backfill_credential_gateway_bindings, migrations.RunPython.noop),
    ]
