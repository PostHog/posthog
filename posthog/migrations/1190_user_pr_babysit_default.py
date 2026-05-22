from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1189_file_system_shortcut_order_index"),
    ]

    # db_default keeps the Postgres-level DEFAULT (Django would otherwise emit
    # `ALTER COLUMN ... DROP DEFAULT` right after ADD COLUMN, because it treats
    # plain `default=` as a Python-only concern). The DB default matters because
    # (a) posthog_user has non-Django writers in rust/ and nodejs/ that INSERT
    # without listing this column, and (b) the test DB is created from model
    # definitions (see posthog/management/commands/setup_test_environment.py
    # disable_migrations), so without db_default the CREATE TABLE in tests
    # would omit the default entirely and break those writers.
    operations = [
        migrations.AddField(
            model_name="user",
            name="pr_babysit_default",
            field=models.BooleanField(
                blank=False,
                db_default=True,
                default=True,
                help_text=(
                    "Default value of the per-task 'watch CI after PR opens' (PR babysitting) toggle. "
                    "Tasks that don't explicitly set the per-task override inherit this."
                ),
                null=False,
            ),
        ),
    ]
