import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1006_resource_transfer_duplicated_resource_id"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="resourcetransfer",
                    name="created_by",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    """
                    ALTER TABLE "posthog_resourcetransfer" ADD COLUMN "created_by_id" integer NULL CONSTRAINT "posthog_resourcetran_created_by_id_cfdd93a0_fk_posthog_u" REFERENCES "posthog_user"("id") DEFERRABLE INITIALLY DEFERRED;  -- existing-table-constraint-ignore
                    SET CONSTRAINTS "posthog_resourcetran_created_by_id_cfdd93a0_fk_posthog_u" IMMEDIATE;  -- existing-table-constraint-ignore
                    """,
                    reverse_sql="""
                        ALTER TABLE "posthog_resourcetransfer" DROP COLUMN IF EXISTS "created_by_id";
                    """,
                ),
            ],
        ),
    ]
