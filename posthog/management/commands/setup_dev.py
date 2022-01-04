from django.core.management.base import BaseCommand
from django.db import transaction

from posthog.demo import prepare_demo
from posthog.models import PersonalAPIKey

DEV_EMAIL = "test@posthog.com"
DEV_PASSWORD = "12345678"


class Command(BaseCommand):
    help = "Set up the instance for development/review with demo data"

    def handle(self, *args, **options):
        with transaction.atomic():
            organization, team, user = prepare_demo(
                email=DEV_EMAIL,
                password=DEV_PASSWORD,
                first_name="Jane Doe",
                team_fields={"api_token": "e2e_token_1239",},
            )
            PersonalAPIKey.objects.create(user=user, label="e2e_demo_api_key key", value="e2e_demo_api_key")
        print(f"Created user {DEV_EMAIL} with password {DEV_PASSWORD}")
