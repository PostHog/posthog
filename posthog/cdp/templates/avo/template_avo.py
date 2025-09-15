import dataclasses
from copy import deepcopy

from posthog.hogql.escape_sql import escape_hogql_string

from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC, HogFunctionTemplateMigrator

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-avo",
    name="Avo",
    description="Send events to Avo",
    icon_url="/static/services/avo.png",
    category=["Analytics"],
    code_language="hog",
    code="""
if (empty(inputs.apiKey) or empty(inputs.environment)) {
    print('API Key and environment has to be set. Skipping...')
    return
}

let avoEvent := {
    'apiKey': inputs.apiKey,
    'env': inputs.environment,
    'appName': inputs.appName,
    'sessionId': event.properties.$session_id ?? generateUUIDv4(),
    'createdAt': toString(toDateTime(toUnixTimestamp(now()))),
    'avoFunction': false,
    'eventId': null,
    'eventHash': null,
    'appVersion': '1.0.0',
    'libVersion': '1.0.0',
    'libPlatform': 'node',
    'trackingId': '',
    'samplingRate': 1,
    'type': 'event',
    'eventName': event.event,
    'messageId': event.uuid,
    'eventProperties': []
}

fun getPropValueType(propValue) {
    let propType := typeof(propValue)
    if (propValue == null) {
        return 'null'
    } else if (propType == 'string') {
        return 'string'
    } else if (propType == 'integer') {
        return 'int'
    } else if (propType == 'float') {
        return 'float'
    } else if (propType == 'boolean') {
        return 'boolean'
    } else if (propType == 'object') {
        return 'object'
    } else if (propType == 'array') {
        return 'list'
    } else {
        return propType
    }
}

for (let key, value in event.properties) {
    let excludeProperties := arrayMap(x -> trim(x), splitByString(',', inputs.excludeProperties))
    let includeProperties := arrayMap(x -> trim(x), splitByString(',', inputs.includeProperties))
    let isExcluded := has(excludeProperties, key)
    let isIncluded := includeProperties[1] == '' or has(includeProperties, key)

    if (not (key like '$%' or isExcluded or not isIncluded)) {
        avoEvent.eventProperties := arrayPushBack(avoEvent.eventProperties, { 'propertyName': key, 'propertyType': getPropValueType(value) })
    }
}

fetch('https://api.avo.app/inspector/posthog/v1/track', {
    'method': 'POST',
    'headers': {
        'env': inputs.environment,
        'api-key': inputs.apiKey,
        'content-type': 'application/json',
        'accept': 'application/json',
    },
    'body': [avoEvent]
})
""".strip(),
    inputs_schema=[
        {
            "key": "apiKey",
            "type": "string",
            "label": "Avo API Key",
            "description": "Avo source API key",
            "default": "",
            "secret": True,
            "required": True,
        },
        {
            "key": "environment",
            "type": "string",
            "label": "Environment",
            "description": "Environment name",
            "default": "dev",
            "secret": False,
            "required": False,
        },
        {
            "key": "appName",
            "type": "string",
            "label": "App name",
            "description": "App name",
            "default": "PostHog",
            "secret": False,
            "required": False,
        },
        {
            "key": "excludeProperties",
            "type": "string",
            "label": "Properties to exclude",
            "description": "Comma-separated list of event properties that will not be sent to Avo.",
            "default": "",
            "secret": False,
            "required": False,
        },
        {
            "key": "includeProperties",
            "type": "string",
            "label": "Properties to include",
            "description": "Comma separated list of event properties to send to Avo (will send all if left empty).",
            "default": "",
            "secret": False,
            "required": False,
        },
    ],
)


class TemplateAvoMigrator(HogFunctionTemplateMigrator):
    plugin_url = "https://github.com/PostHog/posthog-avo-plugin"

    @classmethod
    def migrate(cls, obj):
        hf = deepcopy(dataclasses.asdict(template))
        hf["hog"] = hf["code"]
        del hf["code"]

        apiKey = obj.config.get("avoApiKey", "")
        environment = obj.config.get("environment", "dev")
        appName = obj.config.get("appName", "PostHog")
        excludeEvents = obj.config.get("excludeEvents", "")
        includeEvents = obj.config.get("includeEvents", "")
        excludeProperties = obj.config.get("excludeProperties", "")
        includeProperties = obj.config.get("includeProperties", "")

        hf["filters"] = {}
        hf["filters"]["events"] = []

        events_to_include = [event.strip() for event in includeEvents.split(",") if event.strip()]
        events_to_exclude = [event.strip() for event in excludeEvents.split(",") if event.strip()]

        if events_to_include:
            hf["filters"]["events"] = [
                {"id": event, "name": event, "type": "events", "order": 0} for event in events_to_include
            ]
        elif events_to_exclude:
            event_string = ", ".join(escape_hogql_string(event) for event in events_to_exclude)
            hf["filters"]["events"] = [
                {
                    "id": None,
                    "name": "All events",
                    "type": "events",
                    "order": 0,
                    "properties": [{"key": f"event not in ({event_string})", "type": "hogql"}],
                }
            ]

        hf["inputs"] = {
            "apiKey": {"value": apiKey},
            "environment": {"value": environment},
            "appName": {"value": appName},
            "excludeProperties": {"value": excludeProperties},
            "includeProperties": {"value": includeProperties},
        }

        return hf
