from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("agent_platform", "0011_agentrevision_skill_refs"),
    ]

    operations = [
        migrations.AddField(
            model_name="agentsession",
            name="search_text",
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="agentsession",
            name="turn_count",
            field=models.IntegerField(db_default=0, default=0),
        ),
    ]
