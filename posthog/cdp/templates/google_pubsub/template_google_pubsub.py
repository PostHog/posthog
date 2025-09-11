import json
import dataclasses
from copy import deepcopy

from posthog.hogql.escape_sql import escape_hogql_string

from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC, HogFunctionTemplateMigrator
from posthog.models.integration import GoogleCloudIntegration

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-google-pubsub",
    name="Google Pub/Sub",
    description="Send data to a Google Pub/Sub topic",
    icon_url="/static/services/google-cloud.png",
    category=["Custom"],
    code_language="hog",
    code="""
let headers := () -> {
  'Authorization': f'Bearer {inputs.auth.access_token}',
  'Content-Type': 'application/json'
}
let message := () -> {
  'messageId': event.uuid,
  'data': base64Encode(jsonStringify(inputs.payload)),
  'attributes': inputs.attributes
}
let res := fetch(f'https://pubsub.googleapis.com/v1/{inputs.topicId}:publish', {
  'method': 'POST',
  'headers': headers(),
  'body': jsonStringify({ 'messages': [message()] })
})

if (res.status >= 200 and res.status < 300) {
  print('Event sent successfully!')
} else {
  throw Error(f'Error from pubsub.googleapis.com (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "auth",
            "type": "integration",
            "integration": "google-pubsub",
            "label": "Google Cloud service account",
            "secret": False,
            "required": True,
        },
        {
            "key": "topicId",
            "type": "string",
            "label": "Topic name",
            "secret": False,
            "required": True,
        },
        {
            "key": "payload",
            "type": "json",
            "label": "Message Payload",
            "default": {"event": "{event}", "person": "{person}"},
            "secret": False,
            "required": False,
        },
        {
            "key": "attributes",
            "type": "json",
            "label": "Attributes",
            "default": {},
            "secret": False,
            "required": False,
        },
    ],
)


class TemplateGooglePubSubMigrator(HogFunctionTemplateMigrator):
    plugin_url = "https://github.com/PostHog/pubsub-plugin"

    @classmethod
    def migrate(cls, obj):
        hf = deepcopy(dataclasses.asdict(template))
        hf["hog"] = hf["code"]
        del hf["code"]

        exportEventsToIgnore = [x.strip() for x in obj.config.get("exportEventsToIgnore", "").split(",") if x]
        topicId = obj.config.get("topicId", "")

        from posthog.models.plugin import PluginAttachment

        attachment: PluginAttachment | None = PluginAttachment.objects.filter(
            plugin_config=obj, key="googleCloudKeyJson"
        ).first()
        if not attachment:
            raise Exception("Google Cloud Key JSON not found")

        keyFile = json.loads(attachment.contents.decode("UTF-8"))  # type: ignore
        integration = GoogleCloudIntegration.integration_from_key("google-pubsub", keyFile, obj.team.pk)

        hf["filters"] = {}
        if exportEventsToIgnore:
            event_names = ", ".join([escape_hogql_string(event) for event in exportEventsToIgnore])
            query = f"event not in ({event_names})"
            hf["filters"]["events"] = [
                {
                    "id": None,
                    "name": "All events",
                    "type": "events",
                    "order": 0,
                    "properties": [{"key": query, "type": "hogql"}],
                }
            ]

        hf["inputs"] = {
            "topicId": {"value": topicId},
            "payload": {
                "value": {
                    "event": "{event.event}",
                    "distinct_id": "{event.distinct_id}",
                    "elements_chain": "{event.elements_chain}",
                    "timestamp": "{event.timestamp}",
                    "uuid": "{event.uuid}",
                    "properties": "{event.properties}",
                    "person_id": "{person.id}",
                    "person_properties": "{person.properties}",
                }
            },
            "auth": {"value": integration.id},
            "attributes": {"value": {}},
        }

        return hf
