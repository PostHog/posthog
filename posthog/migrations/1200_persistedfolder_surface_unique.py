from django.db import migrations, models
from django.db.models import Value
from django.db.models.expressions import F
from django.db.models.functions import Coalesce

from posthog.migration_helpers import CreateIndexConcurrently


class Migration(migrations.Migration):
    # Concurrent index builds cannot run inside a transaction.
    atomic = False

    dependencies = [
        ("posthog", "1199_filesystem_related_surface"),
    ]

    operations = [
        # Add the surface-aware unique index BEFORE dropping the old (team, user, type) constraint
        # (done in the next migration), so the table is never left without uniqueness protection.
        # COALESCE(surface, 'web') matches the NULL == "web" read rule, so a legacy NULL row and a
        # new explicit-"web" row can never both exist for the same (team, user, type). Build it
        # concurrently via the helper (lock_timeout disabled, idempotent, invalid-leftover recovery).
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="persistedfolder",
                    constraint=models.UniqueConstraint(
                        F("team_id"),
                        F("user_id"),
                        F("type"),
                        Coalesce(F("surface"), Value("web")),
                        name="posthog_pf_team_user_type_surface_uniq",
                    ),
                ),
            ],
            database_operations=[
                CreateIndexConcurrently(
                    index_name="posthog_pf_team_user_type_surface_uniq",
                    table_name="posthog_persistedfolder",
                    columns="(team_id, user_id, type, COALESCE(surface, 'web'))",
                    unique=True,
                ),
            ],
        ),
    ]
