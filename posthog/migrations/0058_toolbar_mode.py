# Generated by Django 3.0.5 on 2020-06-08 09:41

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0057_action_updated_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='toolbar_mode',
            field=models.CharField(blank=True, default='default', max_length=200, null=True),
        ),
    ]
