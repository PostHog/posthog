# Generated by Django 3.0.7 on 2020-06-23 17:13

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0062_team_anonymize_ips'),
    ]

    operations = [
        migrations.AddField(
            model_name='team',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=None),
            preserve_default=False,
        ),
    ]
