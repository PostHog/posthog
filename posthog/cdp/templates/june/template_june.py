from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="stable",
    free=False,
    type="destination",
    id="template-june",
    name="June.so",
    description="Send events to June.so ",
    icon_url="/static/services/june.png",
    category=["Analytics"],
    code_language="hog",
    code="""
let type := 'track'

if (event.event in ('$identify', '$set')) {
    type := 'identify'
} else if (event.event in ('$pageview', '$screen')) {
    type := 'page'
}

let context := {
    'app': {},
    'campaign': {},
    'device': {},
    'os': {},
    'referrer': {},
    'screen': {}
}

if (not empty(event.properties.$app_build)) context.app.build := event.properties.$app_build
if (not empty(event.properties.$app_version)) context.app.version := event.properties.$app_version
if (not empty(event.properties.$app_name)) context.app.name := event.properties.$app_name
if (not empty(event.properties.utm_campaign)) context.campaign.name := event.properties.utm_campaign
if (not empty(event.properties.utm_content)) context.campaign.content := event.properties.utm_content
if (not empty(event.properties.utm_medium)) context.campaign.medium := event.properties.utm_medium
if (not empty(event.properties.utm_source)) context.campaign.source := event.properties.utm_source
if (not empty(event.properties.utm_term)) context.campaign.term := event.properties.utm_term
if (not empty(event.properties.$device_id)) context.device.id := event.properties.$device_id
if (not empty(event.properties.$device_manufacturer)) context.device.manufacturer := event.properties.$device_manufacturer
if (not empty(event.properties.$device_model)) context.device.model := event.properties.$device_model
if (not empty(event.properties.$os_name)) context.device.name := event.properties.$os_name
if (not empty(event.properties.$os_version)) context.device.version := event.properties.$os_version
if (not empty(event.properties.$device_type)) context.device.type := event.properties.$device_type
if (not empty(event.properties.$ip)) context.ip := event.properties.$ip
if (not empty(event.properties.$browser_language)) context.locale := event.properties.$browser_language
if (not empty(event.properties.$os)) context.os.name := event.properties.$os
if (not empty(event.properties.$os_version)) context.os.version := event.properties.$os_version
if (not empty(event.properties.$referrer)) context.referrer.url := event.properties.$referrer
if (not empty(event.properties.$screen_height)) context.screen.height := event.properties.$screen_height
if (not empty(event.properties.$screen_width)) context.screen.width := event.properties.$screen_width
if (not empty(event.properties.$geoip_time_zone)) context.timezone := event.properties.$geoip_time_zone
if (not empty(event.properties.$raw_user_agent)) context.userAgent := event.properties.$raw_user_agent

let properties := {}

if (not empty(event.properties.$current_url)) properties.url := event.properties.$current_url
if (not empty(event.properties.$pathname)) properties.path := event.properties.$pathname
if (not empty(event.properties.title)) properties.title := event.properties.title
if (not empty(event.properties.$referrer)) properties.referrer := event.properties.$referrer
if (not empty(event.properties.$current_url)) {
    if (not empty(splitByString('?', event.properties.$current_url)[2])) {
        properties.search := f'?{splitByString('?', event.properties.$current_url)[2]}'
    }
}

let traits := {}

for (let key, value in inputs.properties) {
    if (not empty(value)) {
        traits[key] := value
    }
}

if (inputs.include_all_properties) {
    for (let key, value in (type == 'identify' ? person.properties : event.properties)) {
        if (not empty(value) and not key like '$%') {
            traits[key] := value
        }
    }
}

let body := {
    'properties': properties,
    'traits': traits,
    'timestamp': event.timestamp,
    'context': context,
    'messageId': event.uuid
}

if (type == 'track') body.event := event.event
if (event.properties.$is_identified) {
    body.userId := event.distinct_id
    if (not empty(event.properties.$anon_distinct_id)) body.anonymousId := event.properties.$anon_distinct_id
} else {
    body.anonymousId := event.distinct_id
}

let res := fetch(f'https://api.june.so/sdk/{type}', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Basic {inputs.apiKey}',
        'Content-Type': 'application/json'
    },
    'body': body
})

if (res.status >= 400) {
    throw Error(f'Error from api.june.so (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "apiKey",
            "type": "string",
            "label": "June.so Write API key",
            "secret": True,
            "required": True,
        },
        {
            "key": "include_all_properties",
            "type": "boolean",
            "label": "Include all properties as attributes",
            "description": "If set, all event properties will be included as traits. Individual traits can be overridden below. For identify events the Person properties will be used.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Trait mapping",
            "description": "Map of June.so traits and their values. You can use the filters section to filter out unwanted events.",
            "default": {
                "email": "{person.properties.email}",
                "name": "{person.properties.name}",
                "phone": "{person.properties.phone}",
            },
            "secret": False,
            "required": False,
        },
    ],
    filters={
        "events": [],
        "actions": [],
        "filter_test_accounts": False,
    },
)
