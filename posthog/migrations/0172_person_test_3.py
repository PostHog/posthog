# Generated by Django 3.2.5 on 2021-09-27 10:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0171_person_properties_2"),
    ]

    operations = [
        migrations.AddField(
            model_name="person",
            name="test_3",
            field=models.CharField(default="lol", max_length=400),
            preserve_default=False,
        ),
    ]
