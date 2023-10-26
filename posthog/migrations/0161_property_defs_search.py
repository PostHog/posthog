# Generated by Django 3.1.12 on 2021-07-16 13:04

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0160_organization_domain_whitelist"),
    ]

    operations = [
        TrigramExtension(),
        migrations.AddIndex(
            model_name="eventdefinition",
            index=GinIndex(
                fields=["name"],
                name="index_event_definition_name",
                opclasses=["gin_trgm_ops"],
            ),
        ),
        migrations.AddIndex(
            model_name="propertydefinition",
            index=GinIndex(
                fields=["name"],
                name="index_property_definition_name",
                opclasses=["gin_trgm_ops"],
            ),
        ),
    ]
