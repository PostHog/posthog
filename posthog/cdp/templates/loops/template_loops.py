import dataclasses
from copy import deepcopy
from posthog.cdp.templates.hog_function_template import HogFunctionTemplate, HogFunctionTemplateMigrator

template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-loops",
    name="Loops",
    description="Send events to Loops",
    icon_url="/static/services/loops.png",
    category=["Email Marketing"],
    hog="""
let apiKey := inputs.apiKey

let payload := {
    'userId': event.distinct_id,
    'eventName': event.event == '$set' ? '$identify' : event.event,
    'email': person.properties.email
}
for (let key, value in person.properties) {
    payload[key] := value
}
fetch('https://app.loops.so/api/v1/events/send', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {apiKey}',
    },
    'body': payload
})
""".strip(),
    inputs_schema=[
        {
            "key": "apiKey",
            "type": "string",
            "label": "Loops API Key",
            "description": "Loops API Key",
            "default": "",
            "secret": True,
            "required": True,
        }
    ],
    filters={
        "events": [
            {"id": "$identify", "name": "$identify", "type": "events", "order": 0},
            {"id": "$set", "name": "$set", "type": "events", "order": 1},
        ],
        "actions": [],
        "filter_test_accounts": True,
    },
)


class TemplateLoopsMigrator(HogFunctionTemplateMigrator):
    plugin_url = "https://github.com/PostHog/posthog-loops-plugin"

    @classmethod
    def migrate(cls, obj):
        hf = deepcopy(dataclasses.asdict(template))

        apiKey = obj.config.get("apiKey", "")
        trackedEvents = obj.config.get("trackedEvents", "")
        shouldTrackIdentify = obj.config.get("shouldTrackIdentify", "yes")

        hf["filters"] = {}
        hf["filters"]["events"] = []

        events_to_filter = [event.strip() for event in trackedEvents.split(",") if event.strip()]

        if events_to_filter:
            hf["filters"]["events"] = [
                {"id": event, "name": event, "type": "events", "order": 0} for event in events_to_filter
            ]

        if shouldTrackIdentify == "yes" and len(hf["filters"]["events"]) >= 1:
            hf["filters"]["events"].append({"id": "$identify", "name": "$identify", "type": "events", "order": 0})
            hf["filters"]["events"].append({"id": "$set", "name": "$set", "type": "events", "order": 1})

        hf["inputs"] = {
            "apiKey": {"value": apiKey},
        }

        return hf
