from django.db import migrations

from posthog.migration_helpers import chunked_queryset_iterator


def merge_catalog_into_server(apps, schema_editor):
    """Copy each DuckLakeCatalog's connection + bucket onto its org's DuckgresServer.

    Every catalog maps 1:1 to an existing server by organization_id (verified against prod).
    The catalog's bucket wins over any value already on the server — this preserves the older
    catalog-first runtime resolution, so a team's backfill keeps reading the same bucket it
    reads today. The control plane self-heal still reconciles server.bucket on read afterward.
    """
    DuckLakeCatalog = apps.get_model("posthog", "DuckLakeCatalog")
    DuckgresServer = apps.get_model("posthog", "DuckgresServer")

    servers_by_org = {server.organization_id: server for server in DuckgresServer.objects.all()}
    for catalog in chunked_queryset_iterator(DuckLakeCatalog.objects.all()):
        server = servers_by_org.get(catalog.organization_id)
        if server is None:
            # No server for this org — nothing to merge onto (none in prod).
            continue
        server.catalog_host = catalog.db_host
        server.catalog_port = catalog.db_port
        server.catalog_database = catalog.db_database
        server.catalog_username = catalog.db_username
        server.catalog_password = catalog.db_password
        update_fields = ["catalog_host", "catalog_port", "catalog_database", "catalog_username", "catalog_password"]
        if catalog.bucket:
            server.bucket = catalog.bucket
            server.bucket_region = catalog.bucket_region
            update_fields += ["bucket", "bucket_region"]
        server.save(update_fields=update_fields)


def merge_backfill_into_server_team(apps, schema_editor):
    """Copy each DuckLakeBackfill onto the team's existing DuckgresServerTeam row.

    The backfill teams are the exact set of server-team teams (verified against prod), so every
    backfill maps 1:1 to an existing membership row. A backfill whose team has no membership row
    (none in prod) is skipped — DuckgresServerTeam.server is non-null and there is nothing to
    attach it to.
    """
    DuckLakeBackfill = apps.get_model("posthog", "DuckLakeBackfill")
    DuckgresServerTeam = apps.get_model("posthog", "DuckgresServerTeam")

    links_by_team = {link.team_id: link for link in DuckgresServerTeam.objects.all()}
    for backfill in chunked_queryset_iterator(DuckLakeBackfill.objects.all()):
        link = links_by_team.get(backfill.team_id)
        if link is None:
            continue
        link.backfill_enabled = backfill.enabled
        link.table_suffix = backfill.table_suffix
        link.earliest_event_date = backfill.earliest_event_date
        link.save(update_fields=["backfill_enabled", "table_suffix", "earliest_event_date"])


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1240_consolidate_duckgres_models"),
    ]

    operations = [
        migrations.RunPython(merge_catalog_into_server, migrations.RunPython.noop),
        migrations.RunPython(merge_backfill_into_server_team, migrations.RunPython.noop),
    ]
