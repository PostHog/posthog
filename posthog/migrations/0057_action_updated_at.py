# Generated by Django 3.0.5 on 2020-05-30 01:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0056_auto_20200522_1024"),
    ]

    operations = [
        migrations.AddField(model_name="action", name="updated_at", field=models.DateTimeField(auto_now=True),),
    ]
