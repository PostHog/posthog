# Generated by Django 3.2.16 on 2023-03-10 16:03

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0308_add_indirect_person_override_constraints"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="autocapture_opt_out",
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
