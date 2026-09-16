from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "1360_validate_taggeditem_experiment_fk"),
    ]

    operations = [
        migrations.AlterField(
            model_name="asyncdeletion",
            name="deletion_type",
            field=models.PositiveSmallIntegerField(
                choices=[
                    (0, "Team"),
                    (1, "Person"),
                    (2, "Group"),
                    (3, "Cohort Stale"),
                    (4, "Cohort Full"),
                    (5, "Event"),
                ]
            ),
        ),
    ]
