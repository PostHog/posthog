#!/usr/bin/env python3
# ruff: noqa: T201 — standalone CLI payload, print is the output channel
"""Mint a personal API key for the seeded demo user, printing APIKEY=<value>.

TEMPORARY preview-seed payload for the PR #74534 / #74545 comparison. Runs
inside the box's web image; mirrors PersonalAPIKeySerializer.create so the
key authenticates like a UI-minted one.
"""

import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from posthog.models import PersonalAPIKey, User  # noqa: E402
from posthog.models.utils import generate_random_token_personal, hash_key_value, mask_key_value  # noqa: E402

user = User.objects.get(email="test@posthog.com")
value = generate_random_token_personal()
PersonalAPIKey.objects.create(
    user=user,
    label="preview-seed",
    secure_value=hash_key_value(value),
    mask_value=mask_key_value(value),
    scopes=["*"],
)
print(f"APIKEY={value}")
