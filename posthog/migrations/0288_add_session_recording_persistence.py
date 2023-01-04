# Generated by Django 3.2.16 on 2023-01-04 12:26

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0287_add_session_recording_model'),
    ]

    operations = [
        migrations.AddField(
            model_name='sessionrecording',
            name='click_count',
            field=models.IntegerField(null=True),
        ),
        migrations.AddField(
            model_name='sessionrecording',
            name='deleted',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='sessionrecording',
            name='distinct_id',
            field=models.CharField(blank=True, max_length=400, null=True),
        ),
        migrations.AddField(
            model_name='sessionrecording',
            name='duration',
            field=models.IntegerField(null=True),
        ),
        migrations.AddField(
            model_name='sessionrecording',
            name='end_time',
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name='sessionrecording',
            name='keypress_count',
            field=models.IntegerField(null=True),
        ),
        migrations.AddField(
            model_name='sessionrecording',
            name='object_storage_path',
            field=models.CharField(blank=True, max_length=200, null=True),
        ),
        migrations.AddField(
            model_name='sessionrecording',
            name='start_time',
            field=models.DateTimeField(null=True),
        ),
        migrations.AddField(
            model_name='sessionrecording',
            name='start_url',
            field=models.CharField(max_length=512, null=True),
        ),
    ]
