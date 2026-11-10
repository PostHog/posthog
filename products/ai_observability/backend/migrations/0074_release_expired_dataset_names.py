from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("ai_observability", "0073_dataset_live_name_uniqueness")]

    operations = [
        migrations.RemoveConstraint(
            model_name="dataset",
            name="uniq_llma_dataset_v2_team_name",
        ),
    ]
