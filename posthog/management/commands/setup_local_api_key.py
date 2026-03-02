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

DEV_API_KEY = settings.DEV_API_KEY
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
        parser.add_argument(
            "--scopes",
            nargs="*",
            default=None,
            help="Scopes to grant (e.g. --scopes llm_gateway:read project:read). Omit for no scopes.",
        )
        parser.add_argument(
            "--add-scopes",
            nargs="*",
            default=None,
            help="Scopes to add to an existing key without removing others (e.g. --add-scopes llm_gateway:read).",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("This command can only run with DEBUG=True")
        if settings.CLOUD_DEPLOYMENT:
            raise CommandError("This command cannot run in cloud deployments")

        email = options["email"]
        scopes = options["scopes"]
        add_scopes = options["add_scopes"]

        if scopes is not None and add_scopes is not None:
            raise CommandError("Cannot use --scopes and --add-scopes together")

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            print(f"User with email '{email}' not found")
            return

        secure_value = hash_key_value(DEV_API_KEY)

        existing_key = PersonalAPIKey.objects.filter(secure_value=secure_value).first()
        if existing_key:
            if add_scopes:
                current = set(existing_key.scopes or [])
                merged = sorted(current | set(add_scopes))
                if merged != sorted(current):
                    existing_key.scopes = merged
                    existing_key.save(update_fields=["scopes"])
                    print(f"Added scopes {add_scopes} for user '{existing_key.user.email}'")
                else:
                    print(f"Scopes already present for user '{existing_key.user.email}'")
            elif scopes is not None and existing_key.scopes != scopes:
                existing_key.scopes = scopes or None
                existing_key.save(update_fields=["scopes"])
                print(f"Updated scopes to {scopes} for user '{existing_key.user.email}'")
            else:
                print(f"API key already exists for user '{existing_key.user.email}'")
            print(f"Key: {DEV_API_KEY}")
            return

        PersonalAPIKey.objects.filter(user=user, label=DEV_KEY_LABEL).delete()

        create_scopes = scopes or add_scopes or None

        PersonalAPIKey.objects.create(
            user=user,
            label=DEV_KEY_LABEL,
            secure_value=secure_value,
            mask_value=mask_key_value(DEV_API_KEY),
            scopes=create_scopes,
        )

        print(f"Created personal API key for '{email}'")
        if create_scopes:
            print(f"Scopes: {', '.join(create_scopes)}")
        print(f"Key: {DEV_API_KEY}")
