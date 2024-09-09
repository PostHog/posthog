from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-avo",
    name="Send events to Avo",
    description="Send events to Avo",
    icon_url="/static/services/avo.png",
    hog="""
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
    'eventName': event.name,
    'messageId': event.uuid,
    'eventProperties': []
}

fn getPropValueType(propValue) {
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
