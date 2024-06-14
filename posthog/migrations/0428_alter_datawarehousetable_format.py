# Generated by Django 4.2.11 on 2024-06-14 19:56

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0427_hogfunction_icon_url_hogfunction_template_id"),
    ]

    operations = [
        migrations.AlterField(
            model_name="datawarehousetable",
            name="format",
            field=models.CharField(
                choices=[
                    ("CSV", "CSV"),
                    ("CSVWithNames", "CSVWithNames"),
                    ("Parquet", "Parquet"),
                    ("JSONEachRow", "JSON"),
                ],
                max_length=128,
            ),
        ),
    ]
