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
    id="template-google-cloud-storage",
    name="Google Cloud Storage",
    description="Send data to GCS. This creates a file per event.",
    icon_url="/static/services/google-cloud-storage.png",
    category=["Custom"],
    code_language="hog",
    code="""
let res := fetch(f'https://storage.googleapis.com/upload/storage/v1/b/{encodeURLComponent(inputs.bucketName)}/o?uploadType=media&name={encodeURLComponent(inputs.filename)}', {
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.auth.access_token}',
    'Content-Type': 'application/json'
  },
  'body': inputs.payload
})

if (res.status >= 200 and res.status < 300) {
  print('Event sent successfully!')
} else {
  throw Error('Error sending event', res)
}
""".strip(),
    inputs_schema=[
        {
            "key": "auth",
            "type": "integration",
            "integration": "google-cloud-storage",
            "label": "Google Cloud service account",
            "secret": False,
            "required": True,
        },
        {
            "key": "bucketName",
            "type": "string",
            "label": "Bucket name",
            "secret": False,
            "required": True,
        },
        {
            "key": "filename",
            "type": "string",
            "label": "Filename",
            "default": "{toDate(event.timestamp)}/{event.timestamp}-{event.uuid}.json",
            "secret": False,
            "required": True,
        },
        {
            "key": "payload",
            "type": "string",
            "label": "File contents",
            "default": "{jsonStringify({ 'event': event, 'person': person })}",
            "secret": False,
            "required": True,
        },
    ],
)


class TemplateGoogleCloudStorageMigrator(HogFunctionTemplateMigrator):
    plugin_url = "https://github.com/PostHog/posthog-gcs-plugin"

    @classmethod
    def migrate(cls, obj):
        hf = deepcopy(dataclasses.asdict(template))
        hf["hog"] = hf["code"]
        del hf["code"]

        exportEventsToIgnore = [x.strip() for x in obj.config.get("exportEventsToIgnore", "").split(",") if x]
        bucketName = obj.config.get("bucketName", "")

        from posthog.models.plugin import PluginAttachment

        attachment: PluginAttachment | None = PluginAttachment.objects.filter(
            plugin_config=obj, key="googleCloudKeyJson"
        ).first()
        if not attachment:
            raise Exception("Google Cloud Key JSON not found")

        keyFile = json.loads(attachment.contents.decode("UTF-8"))  # type: ignore
        integration = GoogleCloudIntegration.integration_from_key("google-cloud-storage", keyFile, obj.team.pk)

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
            "bucketName": {"value": bucketName},
            "payload": {
                "value": "uuid,event,properties,elements,people_set,people_set_once,distinct_id,team_id,ip,site_url,timestamp\n"
                + "{event.uuid},{event.event},{jsonStringify(event.properties)},{event.elements_chain},{jsonStringify(event.properties.$set)},{jsonStringify(event.properties.$set_once)},{event.distinct_id},,,,{event.timestamp}"
            },
            "filename": {
                "value": "{toDate(event.timestamp)}/{replaceAll(replaceAll(replaceAll(toString(event.timestamp), '-', ''), ':', ''), 'T', '-')}-{event.uuid}.csv"
            },
            "auth": {"value": integration.id},
        }

        return hf
