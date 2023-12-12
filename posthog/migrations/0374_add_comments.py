# Generated by Django 3.2.19 on 2023-12-12 09:31

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import posthog.models.utils


class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0373_externaldataschema'),
    ]

    operations = [
        migrations.CreateModel(
            name='Comment',
            fields=[
                ('id', models.UUIDField(default=posthog.models.utils.UUIDT, editable=False, primary_key=True, serialize=False)),
                ('content', models.TextField(blank=True, null=True)),
                ('deleted_at', models.DateTimeField(auto_now_add=True)),
                ('version', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('item_id', models.CharField(max_length=72, null=True)),
                ('scope', models.CharField(max_length=79)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('source_comment_id', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='posthog.comment')),
                ('team', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='posthog.team')),
            ],
        ),
        migrations.AddIndex(
            model_name='comment',
            index=models.Index(fields=['team_id', 'scope', 'item_id'], name='posthog_com_team_id_be2206_idx'),
        ),
    ]
