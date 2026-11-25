import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1456_integration_row_version"),
    ]

    # A nullable column with no constraint and no index is a catalog-only change. 1455 adds the
    # foreign key NOT VALID, 1456 validates it, and 1457 builds the index concurrently.
    operations = [
        migrations.AddField(
            model_name="personalapikey",
            name="provisioned_by",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                db_index=False,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="provisioned_personal_api_keys",
                to=settings.OAUTH2_PROVIDER_APPLICATION_MODEL,
            ),
        ),
    ]
