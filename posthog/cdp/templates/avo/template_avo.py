from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-avo",
    name="Send events to Avo",
    description="Send events to Avo",
    icon_url="/static/services/avo.png",
    hog="""
let apiKey := inputs.avoApiKey
let environment := inputs.environment
let appName := inputs.appName

let avoEvent := {
    'apiKey': apiKey,
    'env': environment,
    'appName': appName,
    'sessionId': '6210349f-a6f2-4082-84f4-9696f95c7e10', // Generate Session ID
    'createdAt': '2024-08-30T11:48:18.853Z', // Generate timestamp
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

for (let key, value in event.properties) {
    if (not key like '$%') {
        print(key)
        avoEvent.eventProperties.push({ 'propertyName': key, 'propertyValue': 'string' })
    }
}

// fn getPropValueType(propValue) {
//     let propType = typeof propValue
//     if (propValue == null) {
//         return 'null'
//     } else if (propType === 'string') {
//         return 'string'
//     } else if (propType === 'number' || propType === 'bigint') {
//         if ((propValue + '').indexOf('.') >= 0) {
//             return 'float'
//         } else {
//             return 'int'
//         }
//     } else if (propType === 'boolean') {
//         return 'boolean'
//     } else if (propType === 'object') {
//         if (Array.isArray(propValue)) {
//             return 'list'
//         } else {
//             return 'object'
//         }
//     } else {
//         return propType
//     }
// }

fetch('https://webhook.site/c10b5336-709a-4fe9-96f0-b62edb5f7f5b', {
    'method': 'POST',
    'headers': {
        'env': environment,
        'api-key': apiKey,
        'content-type': 'application/json',
        'accept': 'application/json',
    },
    'body': [avoEvent]
})
""".strip(),
    inputs_schema=[
        {
            "key": "avoApiKey",
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
            "default": "",
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
    ],
)
