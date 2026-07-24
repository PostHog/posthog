from django.db import migrations


def backfill_duckgres_server_teams(apps, schema_editor):
    """Record team↔duckling membership for orgs provisioned before DuckgresServerTeam existed.

    A team's DuckLakeBackfill row is the signal that it uses the org's duckling, so link each
    such team to its org's DuckgresServer. Idempotent (get_or_create on the team OneToOne) and
    leaves table_suffix untouched — legacy teams keep writing to the shared tables. Skips a team
    whose org has no DuckgresServer (nothing to link to).
    """
    DuckLakeBackfill = apps.get_model("posthog", "DuckLakeBackfill")
    DuckgresServer = apps.get_model("posthog", "DuckgresServer")
    DuckgresServerTeam = apps.get_model("posthog", "DuckgresServerTeam")

    servers_by_org = {server.organization_id: server for server in DuckgresServer.objects.all()}
    if not servers_by_org:
        return

    for row in DuckLakeBackfill.objects.values("team_id", "team__organization_id"):
        server = servers_by_org.get(row["team__organization_id"])
        if server is None:
            continue
        DuckgresServerTeam.objects.get_or_create(team_id=row["team_id"], defaults={"server": server})


class Migration(migrations.Migration):
    dependencies = [("posthog", "1232_alter_duckgresserver_bucket_region")]

    operations = [
        migrations.RunPython(backfill_duckgres_server_teams, migrations.RunPython.noop),
    ]
