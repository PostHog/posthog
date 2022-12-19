# Generated by Django 3.2.15 on 2022-10-07 11:23

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0266_add_is_system_field_to_activity_log"),
    ]

    operations = [
        migrations.CreateModel(
            name="Text",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("body", models.CharField(blank=True, max_length=4000, null=True)),
                ("last_modified_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
        ),
        # allow null and add related name to the field
        migrations.AlterField(
            model_name="dashboardtile",
            name="insight",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="dashboard_tiles",
                to="posthog.insight",
            ),
        ),
        migrations.AddField(
            model_name="text",
            name="created_by",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL
            ),
        ),
        migrations.AddField(
            model_name="text",
            name="last_modified_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="modified_text_tiles",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="text",
            name="team",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="posthog.team"),
        ),
        migrations.AddField(
            model_name="dashboardtile",
            name="text",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="dashboard_tiles",
                to="posthog.text",
            ),
        ),
        # dashboard insight pair must be unique if insight is present
        migrations.AddConstraint(
            model_name="dashboardtile",
            constraint=models.UniqueConstraint(
                condition=models.Q(("insight__isnull", False)),
                fields=("dashboard", "insight"),
                name="unique_dashboard_insight",
            ),
        ),
        # dashboard text pair must be unique if text is present
        migrations.AddConstraint(
            model_name="dashboardtile",
            constraint=models.UniqueConstraint(
                condition=models.Q(("text__isnull", False)), fields=("dashboard", "text"), name="unique_dashboard_text"
            ),
        ),
        # can't have both insight and text on a tile
        migrations.AddConstraint(
            model_name="dashboardtile",
            constraint=models.CheckConstraint(
                check=models.Q(
                    models.Q(("insight__isnull", False), ("text__isnull", True)),
                    models.Q(("insight__isnull", True), ("text__isnull", False)),
                    _connector="OR",
                ),
                name="dash_tile_exactly_one_related_object",
            ),
        ),
    ]
