from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    id="template-avo",
    name="Avo inspector",
    description="Export PostHog events to Avo inspector.",
    icon_url="/api/projects/@current/hog_functions/icon/?id=avo.app",
    hog="""
let properties := inputs.properties

let headers := {
    'env': inputs.environment,
    'api-key': inputs.api_key,
    'content-type': 'application/json',
    'accept': 'application/json',
}

let sessionId = '1234' // TODO: randomUUID()
let now = 1234 // TODO: new Date().toISOString()

fn convertPosthogPropsToAvoProps(posthogProps) {
    let avoProps = []
    for (let prop in posthogProps) {
        avoProps.push({
            'key': prop,
            'value': posthogProps[prop],
        })
    }
}


// Compatible with the Avo Rudderstack integration
fn getPropValueType(propValue) {
    let propType = typeof propValue
    if (propValue == null) {
        return 'null'
    } else if (propType === 'string') {
        return 'string'
    } else if (propType === 'number' || propType === 'bigint') {
        if ((propValue + '').indexOf('.') >= 0) {
            return 'float'
        } else {
            return 'int'
        }
    } else if (propType === 'boolean') {
        return 'boolean'
    } else if (propType === 'object') {
        if (Array.isArray(propValue)) {
            return 'list'
        } else {
            return 'object'
        }
    } else {
        return propType
    }
}

let avoEvent = {
    'apiKey': inputs.api_key,
    'env': inputs.environment,
    'appName': config.app_name,
    'sessionId': sessionId,
    'createdAt': now,
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
    'eventProperties': event.properties ? convertPosthogPropsToAvoProps(event.properties) : [],
}


fetch('https://api.avo.app/inspector/posthog/v1/track', {
  'method': 'POST',
  'headers': headers,
  'body': [avoEvent]
})
""".strip(),
    inputs_schema=[
        {
            "key": "api_key",
            "type": "string",
            "label": "API key",
            "secret": True,
            "required": True,
        },
        {
            "key": "environment",
            "type": "string",
            "label": "Environment",
            "default": "dev",
            "secret": False,
            "required": True,
        },
        {
            "key": "app_name",
            "type": "string",
            "label": "App name",
            "default": "PostHog",
            "secret": False,
            "required": True,
        },
    ],
)
