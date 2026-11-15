import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1401_drop_userproductlist_table"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="logo_media",
            field=models.ForeignKey(
                blank=True,
                db_constraint=False,
                db_index=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="posthog.uploadedmedia",
            ),
        ),
    ]
