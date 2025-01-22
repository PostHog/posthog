# Generated by Django 4.2.18 on 2025-01-22 20:51

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0552_turn_off_all_action_webhooks"),
        ("ee", "0020_corememory"),
    ]

    operations = [
        migrations.AddField(
            model_name="accesscontrol",
            name="project",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="access_controls",
                related_query_name="access_controls",
                to="posthog.project",
            ),
        ),
        migrations.AlterField(
            model_name="accesscontrol",
            name="team",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="access_controls",
                related_query_name="access_controls",
                to="posthog.team",
            ),
        ),
    ]
