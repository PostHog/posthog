# Generated by Django 3.0.5 on 2020-05-12 13:50

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0053_dashboard_item_layouts'),
    ]

    operations = [
        migrations.AddField(
            model_name='dashboarditem',
            name='color',
            field=models.CharField(blank=True, max_length=400, null=True),
        ),
    ]
