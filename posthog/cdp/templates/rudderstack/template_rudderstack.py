from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    id="template-rudderstack",
    name="Send data to RudderStack",
    description="Send data to RudderStack",
    icon_url="/static/services/rudderstack.png",
    hog="""
let host := inputs.host
let token := inputs.token
let identifier := inputs.identifier

let rudderPayload := {
    'context': {
        'app': {
            'name': 'PostHogPlugin',
        },
        'os': {
            'name': event.properties.$os
        },
        'browser': event.properties.$browser,
        'browser_version': event.properties.$browser_version,
        'page': {
            'host': event.properties.$host,
            'url': event.properties.$current_url,
            'path': event.properties.$pathname,
            'referrer': event.properties.$referrer,
            'initial_referrer': event.properties.$initial_referrer,
            'referring_domain': event.properties.$referring_domain,
            'initial_referring_domain': event.properties.$initial_referring_domain,
        },
        'screen': {
            'height': event.properties.$screen_height,
            'width': event.properties.$screen_width,
        },
        'library': {
            'name': event.properties.$lib,
            'version': event.properties.$lib_version,
        },
        'ip': event.$ip,
        'active_feature_flags': event.properties.$active_feature_flags,
        'token': event.properties.token
    },
    'channel': 's2s',
    'messageId': event.uuid,
    'originalTimestamp': event.timestamp,
    'userId': identifier,
    'anonymousId': event.properties.$anon_distinct_id ?? event.properties.$device_id ?? event.properties.distinct_id,
    'type': 'track',
    'properties': {},
}

if (event.name in ('$identify', '$set')) {
    rudderPayload.type := 'identify'
    rudderPayload.context.trait := event.properties.$set
    rudderPayload.traits := event.properties.$set
} else if (event.name == '$create_alias') {
    rudderPayload.type := 'alias'
    rudderPayload.userId := event.properties.alias
    rudderPayload.previousId := event.distinct_id
} else if (event.name == '$pageview') {
    rudderPayload.type := 'page'
    rudderPayload.name := event.properties.name
    rudderPayload.properties.host := event.properties.$host
    rudderPayload.properties.url := event.properties.$current_url
    rudderPayload.properties.path := event.properties.$pathname
    rudderPayload.properties.referrer := event.properties.$referrer
    rudderPayload.properties.initial_referrer := event.properties.$initial_referrer
    rudderPayload.properties.referring_domain := event.properties.$referring_domain
    rudderPayload.properties.initial_referring_domain := event.properties.$initial_referring_domain
} else if (event.name == '$autocapture') {
    rudderPayload.type := 'track'
    rudderPayload.event := event.properties.$event_type
} else {
    rudderPayload.type := 'track'
    rudderPayload.event := event.name
}

for (let key, value in event.properties) {
    if (value != null and not key like '$%') {
        rudderPayload.properties[key] := value
    }
}

let payload := {
    'batch': [rudderPayload],
    'sentAt': now()
}
fetch(f'{host}/v1/batch', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
        'Authorization': f'Basic {base64Encode(f'{inputs.token}:')}',
    },
    'body': payload
})
""".strip(),
    inputs_schema=[
        {
            "key": "host",
            "type": "string",
            "label": "Rudderstack host",
            "description": "The destination of the Rudderstack instance",
            "default": "https://hosted.rudderlabs.com",
            "secret": False,
            "required": True,
        },
        {
            "key": "token",
            "type": "string",
            "label": "Write API key",
            "description": "RudderStack Source Writekey",
            "secret": False,
            "required": True,
        },
        {
            "key": "identifier",
            "type": "string",
            "label": "Identifier",
            "default": "{person.uuid}",
            "secret": False,
            "required": True,
        },
    ],
)
