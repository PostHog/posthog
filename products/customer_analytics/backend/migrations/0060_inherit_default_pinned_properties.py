from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        (
            "customer_analytics",
            "0059_teamcustomeranalyticsconfig_default_pinned_properties",
        )
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                UPDATE customer_analytics_usercustomeranalyticsconfig
                SET properties = properties - 'pinned_properties'
                WHERE properties -> 'pinned_properties' = '[]'::jsonb
                  AND cardinality(pinned_custom_property_definition_ids) = 0
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
