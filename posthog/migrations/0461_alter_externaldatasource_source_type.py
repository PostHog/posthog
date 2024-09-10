# Generated by Django 4.2.14 on 2024-08-23 09:54

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0460_alertconfiguration_threshold_alertsubscription_and_more"),
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
                    ("MSSQL", "MSSQL"),
                ],
                max_length=128,
            ),
        ),
    ]
