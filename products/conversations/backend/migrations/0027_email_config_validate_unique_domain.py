from django.db import migrations, models


class Migration(migrations.Migration):
    """Promote the concurrent index to a proper unique constraint (instant)."""

    dependencies = [
        ("conversations", "0026_email_config_unique_domain"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="teamconversationsemailconfig",
                    constraint=models.UniqueConstraint(
                        fields=["domain"],
                        name="unique_email_domain",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        ALTER TABLE "posthog_conversations_email_config"
                            ADD CONSTRAINT "unique_email_domain"
                            UNIQUE USING INDEX "unique_email_domain";
                    """,
                    reverse_sql='ALTER TABLE "posthog_conversations_email_config" DROP CONSTRAINT IF EXISTS "unique_email_domain";',
                ),
            ],
        ),
    ]
