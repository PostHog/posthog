# Generated by Django 4.2.11 on 2024-06-04 15:17

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0420_alert"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
        update posthog_propertydefinition
        set property_type = 'String', is_numerical=False
        where name LIKE '$survey_response%' and property_type = 'Numeric' and type = 1
            """,
            reverse_sql=migrations.RunSQL.noop,
            elidable=True,
        )
    ]
