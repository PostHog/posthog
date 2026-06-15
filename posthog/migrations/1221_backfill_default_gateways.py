from django.db import migrations

# Literal rather than the model constant — migrations must be self-contained and
# stable even if posthog.models.gateway.DEFAULT_GATEWAY_SLUG later changes.
_DEFAULT_SLUG = "default"
_BATCH_SIZE = 2000


def backfill_default_gateways(apps, schema_editor):
    """Seed every canonical (non-child) team with its initial gateway.

    Gateways are project-scoped: child environments share their parent's, so
    only teams with no parent get one. ignore_conflicts (against the unique
    (team, slug) constraint) makes this idempotent and race-safe against the
    provision-on-create signal running concurrently.
    """
    Team = apps.get_model("posthog", "Team")
    Gateway = apps.get_model("posthog", "Gateway")
    # The historical model's default manager is `all_teams` (Gateway sets
    # default_manager_name), so there is no `.objects`; `_default_manager` is unscoped.
    gateways = Gateway._default_manager

    already_provisioned = set(gateways.filter(slug=_DEFAULT_SLUG).values_list("team_id", flat=True))

    batch = []
    for team_id in Team.objects.filter(parent_team_id__isnull=True).values_list("id", flat=True).iterator():
        if team_id in already_provisioned:
            continue
        batch.append(Gateway(team_id=team_id, slug=_DEFAULT_SLUG))
        if len(batch) >= _BATCH_SIZE:
            gateways.bulk_create(batch, ignore_conflicts=True)
            batch = []
    if batch:
        gateways.bulk_create(batch, ignore_conflicts=True)


class Migration(migrations.Migration):
    # Atomic for rollback safety: only inserts into the freshly created (empty)
    # Gateway table, so the single transaction takes no lock other code contends
    # on; batching bounds per-statement size and memory. A failed run rolls back
    # cleanly and re-runs idempotently via ignore_conflicts.

    dependencies = [
        ("posthog", "1220_gateway"),
    ]

    operations = [
        migrations.RunPython(backfill_default_gateways, migrations.RunPython.noop),
    ]
