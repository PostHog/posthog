#!/usr/bin/env python
"""Create a test user, org, team, and personal API key for hobby CI smoke tests.

Run inside the PostHog web container:
    PYTHONPATH=/code:/python-runtime python /tmp/hobby-ci-setup-user.py

Prints "{project_api_token}|||{personal_api_key}" to stdout on success.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.models import Organization, PersonalAPIKey, Team, User  # noqa: E402
from posthog.models.utils import generate_random_token_personal, hash_key_value, mask_key_value  # noqa: E402

org = Organization.objects.first()
if not org:
    org = Organization.objects.create(name="Hobby CI Org")

team = Team.objects.filter(organization=org).first()
if not team:
    team = Team.objects.create(organization=org, name="Default project")

user = User.objects.filter(email="ci@posthog.com").first()
if not user:
    user = User.objects.create_and_join(org, "ci@posthog.com", "CiTest123!", "Hobby CI")

raw_key = generate_random_token_personal()
PersonalAPIKey.objects.filter(user=user, label="ci-smoke-test").delete()
PersonalAPIKey.objects.create(
    user=user,
    label="ci-smoke-test",
    secure_value=hash_key_value(raw_key),
    mask_value=mask_key_value(raw_key),
    scopes=["query:read"],
)
print(f"{team.api_token}|||{raw_key}")  # noqa: T201
