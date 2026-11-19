from django.db import migrations

from posthog.migration_helpers import DropForeignKey


class Migration(migrations.Migration):
    """Take UserProductList out of Django's state and drop its foreign keys.

    Starred products replaced custom products, and nothing reads or writes the table anymore.
    The table stays until a later migration drops it with SafeDropTable.

    The foreign keys go now. Once Django cannot see the model, deleting a team or a user stops
    cascading into this table, and the deferred constraints would fail that delete at COMMIT.
    Both keys point at hot tables, so each drop commits on its own to keep the parent locks short.
    """

    atomic = False

    dependencies = [
        ("posthog", "1397_uploaded_media_dimensions_and_archive"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[migrations.DeleteModel(name="UserProductList")],
            database_operations=[
                DropForeignKey("posthog_userproductlist", column="team_id"),
                DropForeignKey("posthog_userproductlist", column="user_id"),
            ],
        ),
    ]
