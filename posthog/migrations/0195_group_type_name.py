# Generated by Django 3.2.5 on 2022-01-10 12:14

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0194_set_property_type_for_time"),
    ]

    operations = [
        migrations.AddField(
            model_name="grouptypemapping",
            name="name_plural",
            field=models.CharField(blank=True, max_length=400, null=True),
        ),
        migrations.AddField(
            model_name="grouptypemapping",
            name="name_singular",
            field=models.CharField(blank=True, max_length=400, null=True),
        ),
    ]
