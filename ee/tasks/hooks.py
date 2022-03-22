import json

import requests
from celery.task import Task
from django.core.serializers.json import DjangoJSONEncoder


class DeliverHook(Task):
    max_retries = 3
    ignore_result = True

    def run(self, target: str, payload: dict, hook_id: str) -> None:
        try:
            response = requests.post(
                url=target,
                data=json.dumps(payload, cls=DjangoJSONEncoder),
                headers={"Content-Type": "application/json"},
            )
            if response.status_code == 410 and hook_id:
                # Delete hook on our side if it's gone on Zapier's
                from ee.models.hook import Hook

                Hook.objects.filter(id=hook_id).delete()
                return
            if response.status_code >= 500:
                response.raise_for_status()
        except requests.ConnectionError:
            delay_in_seconds = 2 ** self.request.retries
            self.retry(countdown=delay_in_seconds)
