# Generated by Django 3.2.5 on 2022-01-17 20:13

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("ee", "0005_project_based_permissioning"),
    ]

    operations = [
        migrations.AddField(
            model_name="enterpriseeventdefinition",
            name="verified",
            field=models.BooleanField(blank=True, default=False),
        ),
        migrations.AddField(
            model_name="enterpriseeventdefinition",
            name="verified_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="enterpriseeventdefinition",
            name="verified_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="verifying_user",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
