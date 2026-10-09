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

from posthog.accessible_teams import AccessibleTeams  # noqa: E402
from posthog.models import Organization, PersonalAPIKey, Team, User  # noqa: E402
from posthog.personal_api_key_minting import mint_personal_api_key  # noqa: E402

org = Organization.objects.first()
if not org:
    org = Organization.objects.create(name="Hobby CI Org")

team = Team.objects.filter(organization=org).first()
if not team:
    team = Team.objects.create(organization=org, name="Default project")
team.session_recording_opt_in = True
team.save(update_fields=["session_recording_opt_in"])

user = User.objects.filter(email="ci@posthog.com").first()
if not user:
    user = User.objects.create_and_join(org, "ci@posthog.com", "CiTest123!", "Hobby CI")

PersonalAPIKey.objects.filter(user=user, label="ci-smoke-test").delete()
minted = mint_personal_api_key(
    user,
    label="ci-smoke-test",
    scopes=["query:read", "logs:read", "error_tracking:read", "session_recording:read", "tracing:read"],
    teams=AccessibleTeams.all_for(user),
)
print(f"{team.api_token}|||{minted.value}")  # noqa: T201
