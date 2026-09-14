from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Drop the five foreign keys on the ducklake tables, which nothing owns any more.

    1242 took DuckLakeCatalog and DuckLakeBackfill out of Django state and left their tables,
    so old workers could keep reading them through a rolling deploy. The follow-up it names
    never landed. The tables still carry their foreign keys, and no Django model declares a
    relation for any of them.

    A parent delete stops cascading into a relation Django cannot see. The constraints are
    DEFERRABLE INITIALLY DEFERRED with NO ACTION, so the delete finishes its whole cascade and
    Postgres then rejects the transaction at COMMIT. This blocks team deletion, and through
    posthog_ducklakecatalog.organization_id it blocks organization deletion as well.

    The tables stay. Only the constraints go, because the rows are still the last copy of what
    1242 folded in.
    """

    # Not atomic: each DROP CONSTRAINT takes ACCESS EXCLUSIVE on the table it points at, and
    # these point at different ones. In a single transaction a wait on the last parent would
    # hold the locks the earlier statements already took, so a slow lock on a quiet table
    # would stall a hot one. Separate transactions also make a partial run safe to repeat,
    # because DropForeignKey reads the surviving constraints out of pg_constraint.
    atomic = False

    dependencies = [
        ("posthog", "1352_email_lookup_indexes"),
    ]

    operations = [
        DropForeignKey("posthog_ducklakecatalog", column="team_id"),
        DropForeignKey("posthog_ducklakecatalog", column="organization_id"),
        DropForeignKey("posthog_ducklakecatalog", column="created_by_id"),
        DropForeignKey("posthog_ducklakebackfill", column="team_id"),
        DropForeignKey("posthog_ducklakebackfill", column="created_by_id"),
    ]
