from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("posthog", "1332_remove_flatpersonoverride")]

    operations = [
        # State-only: this removes the models, not the tables. The models have had no
        # reader or writer since the plugin-server override writer was removed.
        # Both tables exist twice: in the persons database, whose schema is owned by
        # rust/persons_migrations, and in the main database, where migrations 0291 and
        # 0308 created them. The unused indexes are dropped in rust/persons_migrations.
        # A later DROP TABLE needs one file there and its own RunSQL migration here.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                # PersonOverride first: it holds the foreign keys to PersonOverrideMapping.
                migrations.DeleteModel(
                    name="PersonOverride",
                ),
                migrations.DeleteModel(
                    name="PersonOverrideMapping",
                ),
            ],
        ),
    ]
