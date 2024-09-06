import json

from django.db import models
from posthog.models import Experiment


class WebExperimentManager(models.Manager):
    def get_queryset(self):
        return super().get_queryset().filter(type="web")


class WebExperiment(Experiment):
    objects = WebExperimentManager()

    class Meta:
        proxy = True

    # Converts the `payload` property of a feature flag's filter to something that is readily usable
    # by the web-experiments.ts file in posthog-js
    # Before :
    # {'groups': [{'properties': [], 'rollout_percentage': 100}],
    #   'payloads': {
    #     'variant #0': '{"data": [{"text": "Save Me", "html": "", "selector": "#page > #body > .header .more"}]}',
    #     'variant #1': '{"data": [{"text": "Submit", "html": "", "selector": "#page > #body > .header .more"}]}'},
    #
    #     'multivariate': {
    #       'variants': [
    #         {'key': 'variant #0', 'rollout_percentage': 50},
    #         {'key': 'variant #1', 'rollout_percentage': 50}
    #       ]
    #     }
    # }
    # After :
    # "variants": {
    #     "variant #0": {
    #         "transforms": [
    #             {
    #                 "text": "Save me",
    #                 "html": "",
    #                 "selector": "##page > #body > .header .more"
    #             }
    #         ],
    #         "rollout_percentage": 50
    #     },
    #     "variant #1": {
    #         "transforms": [
    #             {
    #                 "text": "Submit",
    #                 "html": "",
    #                 "selector": "##page > #body > .header .more"
    #             }
    #         ],
    #         "rollout_percentage": 50
    #     }
    # }
    def variants(self):
        experiment = self
        if experiment.feature_flag is None or experiment.feature_flag.filters is None:
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
            serializer_payload = {"transforms": None, "rollout_percentage": rollout_percentage}
            data = payloads.get(key, None)
            if data is not None:
                # The payload of a variant is serialized into a string
                # We need to unmarshal it back into a JSON dict to send it to the client.
                serializer_payload["transforms"] = json.loads(data).get("data", {})

            payloads[key] = serializer_payload
        return payloads
