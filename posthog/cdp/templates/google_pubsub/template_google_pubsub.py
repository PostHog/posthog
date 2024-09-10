import dataclasses
import json
from copy import deepcopy

from posthog.cdp.templates.hog_function_template import HogFunctionTemplate, HogFunctionTemplateMigrator
from posthog.models.integration import GoogleCloudIntegration

template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-google-pubsub",
    name="Google PubSub",
    description="Send data to a Google PubSub topic",
    icon_url="/static/services/google-cloud.png",
    hog="""
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
  print('Error sending event:', res.status, res.body)
}
""".strip(),
    inputs_schema=[
        {
            "key": "auth",
            "type": "integration",
            "integration": "gc-pubsub",
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

        exportEventsToIgnore = obj.config.get("exportEventsToIgnore", "")
        topicId = obj.config.get("topicId", "")

        from posthog.models.plugin import PluginAttachment

        attachment: PluginAttachment | None = PluginAttachment.objects.filter(
            plugin_config=obj, key="googleCloudKeyJson"
        ).first()
        if not attachment:
            raise Exception("Google Cloud Key JSON not found")

        keyFile = json.loads(attachment.contents.decode("UTF-8"))
        integration = GoogleCloudIntegration.integration_from_key("gc-pubsub", keyFile, obj.team.pk)

        hf["filters"] = {}
        if exportEventsToIgnore:
            events = exportEventsToIgnore.split(",")
            if len(events) > 0:
                event_names = ", ".join(["'{}'".format(event.strip()) for event in events])
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
                    "team_id": "{event.team_id}",
                    "ip": "{event.ip}",
                    "site_url": "{event.site_url}",
                    "timestamp": "{event.timestamp}",
                    "uuid": "{event.uuid}",
                    "properties": "{event.properties}",
                    "elements": [],
                    "people_set": "{person.properties}",
                    "people_set_once": {},
                }
            },
            "auth": {"value": integration.id},
        }

        return hf
