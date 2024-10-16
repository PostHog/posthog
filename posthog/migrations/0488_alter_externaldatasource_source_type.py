# Generated by Django 4.2.15 on 2024-10-15 20:28

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0487_team_survey_config"),
    ]

    operations = [
        migrations.AlterField(
            model_name="externaldatasource",
            name="source_type",
            field=models.CharField(
                choices=[
                    ("Stripe", "Stripe"),
                    ("Hubspot", "Hubspot"),
                    ("Postgres", "Postgres"),
                    ("Zendesk", "Zendesk"),
                    ("Snowflake", "Snowflake"),
                    ("Salesforce", "Salesforce"),
                    ("MySQL", "MySQL"),
                    ("PlanetScale", "PlanetScale"),
                    ("MSSQL", "MSSQL"),
                    ("Vitally", "Vitally"),
                    ("BigQuery", "BigQuery"),
                ],
                max_length=128,
            ),
        ),
    ]
