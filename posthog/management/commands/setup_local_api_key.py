# ruff: noqa: T201 allow print statements
"""
Creates a deterministic personal API key for local development.

Usage:
    python manage.py setup_local_api_key

The key value is fixed so it survives database resets.

Safety: Only runs when DEBUG=True and CLOUD_DEPLOYMENT is unset.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from posthog.models import User
from posthog.models.personal_api_key import PersonalAPIKey, hash_key_value
from posthog.models.utils import mask_key_value

# Fixed key value for local development - DO NOT use in production
DEV_API_KEY = "phx_dev_local_test_api_key_1234567890abcdef"
DEV_USER_EMAIL = "test@posthog.com"
DEV_KEY_LABEL = "Local Development Key"


class Command(BaseCommand):
    help = "Create a deterministic personal API key for local development"

    def add_arguments(self, parser):
        parser.add_argument(
            "--email",
            type=str,
            default=DEV_USER_EMAIL,
            help=f"Email of the user to create the key for (default: {DEV_USER_EMAIL})",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only run with DEBUG=True")
        if settings.CLOUD_DEPLOYMENT:
            raise CommandError("This command cannot run in cloud deployments")

        email = options["email"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            print(f"User with email '{email}' not found")
            return

        secure_value = hash_key_value(DEV_API_KEY)

        existing_key = PersonalAPIKey.objects.filter(secure_value=secure_value).first()
        if existing_key:
            print(f"API key already exists for user '{existing_key.user.email}'")
            print(f"Key: {DEV_API_KEY}")
            return

        PersonalAPIKey.objects.filter(user=user, label=DEV_KEY_LABEL).delete()

        PersonalAPIKey.objects.create(
            user=user,
            label=DEV_KEY_LABEL,
            secure_value=secure_value,
            mask_value=mask_key_value(DEV_API_KEY),
        )

        print(f"Created personal API key for '{email}'")
        print(f"Key: {DEV_API_KEY}")
