# Generated by Django 2.2.7 on 2020-01-29 07:03

from django.db import migrations, models

import posthog.models


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0013_element_attr_class"),
    ]

    operations = [
        migrations.AlterModelManagers(name="user", managers=[("objects", posthog.models.UserManager()),],),
        migrations.RemoveField(model_name="user", name="username",),
        migrations.AlterField(
            model_name="user",
            name="email",
            field=models.EmailField(max_length=254, unique=True, verbose_name="email address"),
        ),
    ]
