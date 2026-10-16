from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("autoresearch", "0004_reader_summaries"),
    ]

    operations = [
        # Existing pipelines already write their scores, so they keep doing it. New pipelines start off.
        migrations.AddField(
            model_name="autoresearchpipeline",
            name="write_person_property",
            field=models.BooleanField(
                db_default=True,
                default=False,
                help_text="Whether live scoring writes the champion's score to output_person_property on each scored person",
            ),
        ),
        migrations.AlterField(
            model_name="autoresearchpipeline",
            name="write_person_property",
            field=models.BooleanField(
                db_default=False,
                default=False,
                help_text="Whether live scoring writes the champion's score to output_person_property on each scored person",
            ),
        ),
        migrations.AlterField(
            model_name="autoresearchrun",
            name="run_type",
            field=models.CharField(
                choices=[
                    ("inference", "Inference"),
                    ("validation", "Validation"),
                    ("property_cleanup", "Property cleanup"),
                ],
                max_length=20,
            ),
        ),
    ]
