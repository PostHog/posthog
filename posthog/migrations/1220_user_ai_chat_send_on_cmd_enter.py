from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1219_filesystemfoldercontextgeneration"),
    ]

    # Use db_default (not just default=) so the column keeps a real Postgres DEFAULT. Django
    # otherwise emits `ADD COLUMN ... DEFAULT false` then `DROP DEFAULT`, treating default= as
    # Python-only. The DB default is load-bearing for the rust/ and nodejs/ test suites:
    # setup_test_environment builds the test schema straight from model definitions
    # (disable_migrations), and their fixtures raw-INSERT into posthog_user with an explicit
    # column list that omits this field (rust/feature-flags/src/utils/test_utils.rs,
    # nodejs/tests/helpers/sql.ts), so without db_default those INSERTs hit the NOT NULL column
    # with no default.
    operations = [
        migrations.AddField(
            model_name="user",
            name="ai_chat_send_on_cmd_enter",
            field=models.BooleanField(
                blank=False,
                db_default=False,
                default=False,
                help_text="When true, the PostHog AI chat composer sends on Cmd/Ctrl+Enter and Enter inserts a new line. When false, Enter sends.",
                null=False,
            ),
        ),
    ]
