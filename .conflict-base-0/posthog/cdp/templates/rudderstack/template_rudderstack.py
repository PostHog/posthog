import dataclasses
from copy import deepcopy

from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC, HogFunctionTemplateMigrator

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-rudderstack",
    name="RudderStack",
    description="Send data to RudderStack",
    icon_url="/static/services/rudderstack.png",
    category=["Custom"],
    code_language="hog",
    code="""
fun getPayload() {
    let rudderPayload := {
        'context': {
            'app': {
                'name': 'PostHogPlugin',
            },
            'os': {},
            'page': {},
            'screen': {},
            'library': {},
        },
        'channel': 's2s',
        'type': 'track',
        'properties': {},
    }

    if (not empty(event.properties.$os)) rudderPayload.context.os.name := event.properties.$os
    if (not empty(event.properties.$browser)) rudderPayload.context.browser := event.properties.$browser
    if (not empty(event.properties.$browser_version)) rudderPayload.context.browser_version := event.properties.$browser_version
    if (not empty(event.properties.$host)) rudderPayload.context.page.host := event.properties.$host
    if (not empty(event.properties.$current_url)) rudderPayload.context.page.url := event.properties.$current_url
    if (not empty(event.properties.$path)) rudderPayload.context.page.path := event.properties.$path
    if (not empty(event.properties.$referrer)) rudderPayload.context.page.referrer := event.properties.$referrer
    if (not empty(event.properties.$initial_referrer)) rudderPayload.context.page.initial_referrer := event.properties.$initial_referrer
    if (not empty(event.properties.$referring_domain)) rudderPayload.context.page.referring_domain := event.properties.$referring_domain
    if (not empty(event.properties.$initial_referring_domain)) rudderPayload.context.page.initial_referring_domain := event.properties.$initial_referring_domain
    if (not empty(event.properties.$screen_height)) rudderPayload.context.screen.height := event.properties.$screen_height
    if (not empty(event.properties.$screen_width)) rudderPayload.context.screen.width := event.properties.$screen_width
    if (not empty(event.properties.$lib)) rudderPayload.context.library.name := event.properties.$lib
    if (not empty(event.properties.$lib_version)) rudderPayload.context.library.version := event.properties.$lib_version
    if (not empty(event.$ip)) rudderPayload.context.ip := event.$ip
    if (not empty(event.properties.$active_feature_flags)) rudderPayload.context.active_feature_flags := event.properties.$active_feature_flags
    if (not empty(event.properties.token)) rudderPayload.context.token := event.properties.token
    if (not empty(event.uuid)) rudderPayload.messageId := event.uuid
    if (not empty(event.timestamp)) rudderPayload.originalTimestamp := event.timestamp
    if (not empty(inputs.identifier)) rudderPayload.userId := inputs.identifier
    if (not empty(event.properties.$anon_distinct_id ?? event.properties.$device_id ?? event.properties.distinct_id)) rudderPayload.anonymousId := event.properties.$anon_distinct_id ?? event.properties.$device_id ?? event.properties.distinct_id

    if (event.event in ('$identify', '$set')) {
        rudderPayload.type := 'identify'
        if (not empty(event.properties.$set)) rudderPayload.context.trait := event.properties.$set
        if (not empty(event.properties.$set)) rudderPayload.traits := event.properties.$set
    } else if (event.event == '$create_alias') {
        rudderPayload.type := 'alias'
        if (not empty(event.properties.alias)) rudderPayload.userId := event.properties.alias
        if (not empty(event.distinct_id)) rudderPayload.previousId := event.distinct_id
    } else if (event.event == '$pageview') {
        rudderPayload.type := 'page'
        if (not empty(event.properties.name)) rudderPayload.name := event.properties.name
        if (not empty(event.properties.$host)) rudderPayload.properties.host := event.properties.$host
        if (not empty(event.properties.$current_url)) rudderPayload.properties.url := event.properties.$current_url
        if (not empty(event.properties.$pathname)) rudderPayload.properties.path := event.properties.$pathname
        if (not empty(event.properties.$referrer)) rudderPayload.properties.referrer := event.properties.$referrer
        if (not empty(event.properties.$initial_referrer)) rudderPayload.properties.initial_referrer := event.properties.$initial_referrer
        if (not empty(event.properties.$referring_domain)) rudderPayload.properties.referring_domain := event.properties.$referring_domain
        if (not empty(event.properties.$initial_referring_domain)) rudderPayload.properties.initial_referring_domain := event.properties.$initial_referring_domain
    } else if (event.event == '$autocapture') {
        rudderPayload.type := 'track'
        if (not empty(event.properties.$event_type)) rudderPayload.event := event.properties.$event_type
    } else {
        rudderPayload.type := 'track'
        if (not empty(event.event)) rudderPayload.event := event.event
    }

    for (let key, value in event.properties) {
        if (value != null and not key like '$%') {
            rudderPayload.properties[key] := value
        }
    }

    return {
        'method': 'POST',
        'headers': {
            'Content-Type': 'application/json',
            'Authorization': f'Basic {base64Encode(f'{inputs.token}:')}',
        },
        'body': {
            'batch': [rudderPayload],
            'sentAt': now()
        }
    }
}

fetch(f'{replaceAll(inputs.host, '/v1/batch', '')}/v1/batch', getPayload())
""".strip(),
    inputs_schema=[
        {
            "key": "host",
            "type": "string",
            "label": "Rudderstack host",
            "description": "The Rudderstack destination instance",
            "default": "https://hosted.rudderlabs.com",
            "secret": False,
            "required": True,
        },
        {
            "key": "token",
            "type": "string",
            "label": "Write API key",
            "description": "RudderStack Source Writekey",
            "secret": True,
            "required": True,
        },
        {
            "key": "identifier",
            "type": "string",
            "label": "Identifier",
            "default": "{person.id}",
            "secret": False,
            "required": True,
        },
    ],
)


class TemplateRudderstackMigrator(HogFunctionTemplateMigrator):
    plugin_url = "https://github.com/PostHog/rudderstack-posthog-plugin"

    @classmethod
    def migrate(cls, obj):
        hf = deepcopy(dataclasses.asdict(template))
        hf["hog"] = hf["code"]
        del hf["code"]

        host = obj.config.get("dataPlaneUrl", "https://hosted.rudderlabs.com")
        token = obj.config.get("writeKey", "")

        hf["inputs"] = {
            "host": {"value": host},
            "token": {"value": token},
            "identifier": {"value": "{event.properties.$user_id ?? event.distinct_id ?? person.id}"},
        }
        hf["filters"] = {}

        return hf
