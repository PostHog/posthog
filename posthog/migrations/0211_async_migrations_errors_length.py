# Generated by Django 3.2.5 on 2022-02-16 19:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0210_drop_update_person_functions"),
    ]

    operations = [
        migrations.AlterField(model_name="asyncmigrationerror", name="description", field=models.TextField(),),
    ]
