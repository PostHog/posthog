from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from posthog.models import Organization
from posthog.models.ai_training import AITrainingConsent, privacy_enabled, record_training_consent


class Command(BaseCommand):
    help = "Initialize durable AI training consent from organization settings."

    def handle(self, *args: object, **options: object) -> None:
        if not privacy_enabled():
            raise CommandError("AI_RESEARCH_REPLAY_PRIVACY_TABLE is not configured")
        initialized = 0
        for organization_id in Organization.objects.values_list("id", flat=True).iterator(chunk_size=200):
            with transaction.atomic():
                AITrainingConsent.objects.get_or_create(organization_id=organization_id)
                state = AITrainingConsent.objects.select_for_update().get(organization_id=organization_id)
                if state.revision:
                    continue
                allowed = Organization.objects.filter(id=organization_id, is_ai_training_opted_in=True).exists()
                with record_training_consent(organization_id, allowed):
                    pass
                initialized += 1
        self.stdout.write(
            f"Initialized {initialized} organizations. The privacy worker will publish their consent state."
        )
