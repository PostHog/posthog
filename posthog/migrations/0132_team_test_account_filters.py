# Generated by Django 3.0.6 on 2021-02-25 17:58

import os
import re

import django.contrib.postgres.fields.jsonb
from django.db import migrations

__location__ = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))


def get_absolute_path(to: str) -> str:
    """
    Returns an absolute path in the FS based on posthog/posthog (back-end root folder)
    """
    return os.path.join(__location__, to)


class GenericEmails:
    """
    List of generic emails that we don't want to use to filter out test accounts.
    """

    def __init__(self):
        with open(get_absolute_path("../helpers/generic_emails.txt"), "r") as f:
            self.emails = {x.rstrip(): True for x in f}

    def is_generic(self, email: str) -> bool:
        at_location = email.find("@")
        if at_location == -1:
            return False
        return self.emails.get(email[at_location + 1 :], False)


def forward(apps, schema_editor):
    Team = apps.get_model("posthog", "Team")

    for team in Team.objects.all():
        filters = [
            {
                "key": "$host",
                "operator": "is_not",
                "value": ["localhost:8000", "localhost:5000", "127.0.0.1:8000", "127.0.0.1:3000"],
            },
        ]
        if team.organization:
            example_emails = team.organization.members.only("email")
            generic_emails = GenericEmails()
            example_emails = [email.email for email in example_emails if not generic_emails.is_generic(email.email)]
            if len(example_emails) > 0:
                example_email = re.search(r"@[\w.]+", example_emails[0])
                if example_email:
                    filters += [
                        {"key": "email", "operator": "not_icontains", "value": example_email.group(), "type": "person"},
                    ]
        team.test_account_filters = filters
        team.save()


def reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("posthog", "0131_add_plugins_updated_created_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="team",
            name="test_account_filters",
            field=django.contrib.postgres.fields.jsonb.JSONField(default=list),
        ),
        migrations.RunPython(forward, reverse),
    ]
