from typing import Any, Optional
import requests
import json
from celery import shared_task
from django.apps import apps
from django.conf import settings
from django.db.models import Model
from rest_hooks.models import Hook


@shared_task
def deliver_hook(url: str, payload: Any, instance_id: Optional[int] = None, hook_id: Optional[int] = None):
    response = requests.post(url=url, data=json.dumps(payload), headers={"Content-Type": "application/json"})
    if response.status_code >= 500:
        response.raise_for_status()


def deliver_hook_wrapper(target: str, payload: Any, instance: Optional[Model], hook: Hook):
    # Instance is None if using custom event, not built-in
    instance_id = instance.id if instance is not None else None
    # Pass IDs not objects because using pickle for objects is a bad thing
    deliver_hook.delay(target=target, payload=payload, instance_id=instance_id, hook_id=hook.id)
