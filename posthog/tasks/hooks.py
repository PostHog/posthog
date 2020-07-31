from typing import Optional
import requests
import json
from celery.task import Task
from django.core.serializers.json import DjangoJSONEncoder
from rest_hooks.utils import get_hook_model


class DeliverHook(Task):
    max_retries = 3

    def run(self, target, payload, instance_id=None, hook_id=None, **kwargs):
        try:
            response = requests.post(
                url=target,
                data=json.dumps(payload, cls=DjangoJSONEncoder),
                headers={"Content-Type": "application/json"},
            )
            if response.status_code == 410 and hook_id:
                # Delete hook on our side if it's gone on Zapier's
                Hook = get_hook_model()
                Hook.objects.filter(id=hook_id).delete()
                return
            if response.status_code >= 500:
                response.raise_for_status()
        except requests.ConnectionError:
            delay_in_seconds = 2 ** self.request.retries
            self.retry(countdown=delay_in_seconds)
