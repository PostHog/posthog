# Generated by Django 4.2.15 on 2024-11-04 11:24

from django.db import migrations

from posthog.hogql_queries.legacy_compatibility.filter_to_query import filter_to_query
from posthog.schema import InsightVizNode


def update_filters_to_queries(apps, schema_editor):
    DashboardTemplate = apps.get_model("posthog", "DashboardTemplate")

    for template in DashboardTemplate.objects.all():
        for tile in template.tiles:
            if "filters" in tile:
                source = filter_to_query(tile["filters"], allow_variables=True)
                query = InsightVizNode(source=source)
                tile["query"] = query.model_dump(exclude_none=True)
                del tile["filters"]
        template.save()


def revert_queries_to_filters(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("posthog", "0529_hog_function_mappings")]

    operations = [
        migrations.RunPython(update_filters_to_queries, revert_queries_to_filters),
    ]
