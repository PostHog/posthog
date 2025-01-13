# Generated by Django 4.2.15 on 2025-01-13 13:00

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("posthog", "0541_usergroup_usergroupmembership_usergroup_members_and_more"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="errortrackingissueassignment",
            name="unique_on_user_and_issue",
        ),
        migrations.AddField(
            model_name="errortrackingissueassignment",
            name="user_group",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to="posthog.usergroup"),
        ),
        migrations.AlterField(
            model_name="errortrackingissueassignment",
            name="user",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL
            ),
        ),
        migrations.AddConstraint(
            model_name="errortrackingissueassignment",
            constraint=models.CheckConstraint(
                check=models.Q(("user__isnull", False), ("user_group__isnull", False), _connector="OR"),
                name="at_least_one_non_null",
            ),
        ),
        migrations.AddConstraint(
            model_name="errortrackingissueassignment",
            constraint=models.CheckConstraint(
                check=models.Q(("user__isnull", False), ("user_group__isnull", False), _negated=True),
                name="only_one_non_null",
            ),
        ),
        migrations.AddConstraint(
            model_name="errortrackingissueassignment",
            constraint=models.UniqueConstraint(fields=("issue",), name="unique_per_issue"),
        ),
    ]
