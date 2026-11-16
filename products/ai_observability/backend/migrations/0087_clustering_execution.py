from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("ai_observability", "0086_clustering_queued_dispatch")]

    operations = [
        migrations.AddField(
            model_name="clusteringrun",
            name="analysis_level",
            field=models.CharField(max_length=20, default="", db_default=""),
        ),
        migrations.AddField(
            model_name="clusteringrun",
            name="is_first_run",
            field=models.BooleanField(default=True, db_default=True),
        ),
    ]
