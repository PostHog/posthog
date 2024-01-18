from celery import shared_task
from django.db import IntegrityError

from posthog.models.prompt.prompt import PromptSequence, UserPromptState
from posthog.models.user import User


@shared_task()
def trigger_prompt_for_user(email: str, sequence_id: int):
    try:
        sequence = PromptSequence.objects.get(pk=sequence_id)
        user = User.objects.get(email=email)
        UserPromptState.objects.get_or_create(user=user, sequence=sequence, step=None)
    except (User.DoesNotExist, IntegrityError):
        pass
