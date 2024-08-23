import json

from django.db import models
from posthog.models import Experiment
# from posthog.models.experiment import ExperimentManager


class WebExperimentManager(models.Manager):
    def get_queryset(self):
        return super(WebExperimentManager, self).get_queryset()

class WebExperiment(Experiment):
    objects = WebExperimentManager()
    # variants = models.JSONField(null=True, blank=True)

    class Meta:
        proxy = True

    def variants(self):
        experiment = self
        if experiment.feature_flag is None:
            return

        if experiment.feature_flag.filters is None:
            return

        multivariate = experiment.feature_flag.filters.get("multivariate", None)
        if multivariate is None:
            return

        variants = multivariate.get("variants", [])
        if len(variants) == 0:
            return

        payloads = experiment.feature_flag.filters.get("payloads", {})
        if len(payloads) == 0:
            return

        if not isinstance(payloads, dict):
            return

        for variant in variants:
            rollout_percentage = variant.get("rollout_percentage", 0)
            key = variant.get("key", None)
            # print('variant is ', key, '  rollout_percentage is ', rollout_percentage, '  payload is ', payloads)
            serializer_payload = {
                'transforms': None,
                'rollout_percentage': rollout_percentage
            }
            data = payloads.get(key, None)
            if data is not None:
                serializer_payload['transforms'] = json.loads(data).get("data", {})

            payloads[key] = serializer_payload
        return payloads

    # def update_payloads(self, payloads):

