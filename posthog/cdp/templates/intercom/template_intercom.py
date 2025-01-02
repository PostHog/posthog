from copy import deepcopy
import dataclasses
from posthog.cdp.templates.hog_function_template import HogFunctionTemplate, HogFunctionTemplateMigrator

template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    type="destination",
    id="template-intercom",
    name="Intercom",
    description="Update contacts in Intercom",
    icon_url="/static/services/intercom.png",
    category=["Customer Success"],
    hog="""
if (empty(inputs.email)) {
    print('No email set. Skipping...')
    return
}

let regions := {
    'US': 'api.intercom.io',
    'EU': 'api.eu.intercom.io',
    'AU': 'api.au.intercom.io',
}

let user := fetch(f'https://{regions[inputs.oauth['app.region']]}/contacts/search', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
        'Intercom-Version': '2.11',
        'Accept': 'application/json',
        'Authorization': f'Bearer {inputs.oauth.access_token}',
    },
    'body': {
        'query': {
            'field': 'email',
            'operator': '=',
            'value': inputs.email
        }
    }
})

let payload := {
    'email': inputs.email
}

if (inputs.include_all_properties) {
    for (let key, value in person.properties) {
        if (not empty(value) and not key like '$%') {
            payload[key] := value
        }
    }
}

for (let key, value in inputs.properties) {
    if (not empty(value)) {
        payload[key] := value
    }
}

let res

if (user.body.total_count == 1) {
    res := fetch(f'https://{regions[inputs.oauth['app.region']]}/contacts/{user.body.data.1.id}', {
        'method': 'PUT',
        'headers': {
            'Content-Type': 'application/json',
            'Intercom-Version': '2.11',
            'Accept': 'application/json',
            'Authorization': f'Bearer {inputs.oauth.access_token}',
        },
        'body': payload
    })
} else if (user.body.total_count == 0) {
    res := fetch(f'https://{regions[inputs.oauth['app.region']]}/contacts', {
        'method': 'POST',
        'headers': {
            'Content-Type': 'application/json',
            'Intercom-Version': '2.11',
            'Accept': 'application/json',
            'Authorization': f'Bearer {inputs.oauth.access_token}',
        },
        'body': payload
    })
} else {
    throw Error('Found multiple contacts with the same email address. Skipping...')
}

if (res.status >= 400) {
    throw Error(f'Error from intercom api (status {res.status}): {res.body}')
} else if (user.status >= 400) {
    throw Error(f'Error from intercom api (status {user.status}): {user.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "oauth",
            "type": "integration",
            "integration": "intercom",
            "label": "Intercom account",
            "requiredScopes": "placeholder",  # intercom scopes are only configurable in the oauth app settings
            "secret": False,
            "required": True,
        },
        {
            "key": "email",
            "type": "string",
            "label": "Email of the user",
            "description": "Where to find the email of the user.",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "include_all_properties",
            "type": "boolean",
            "label": "Include all properties as attributes",
            "description": "If set, all person properties will be included. Individual attributes can be overridden below.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Property mapping",
            "description": "Map of Intercom properties and their values.",
            "default": {
                "name": "{f'{person.properties.first_name} {person.properties.last_name}' == ' ' ? null : f'{person.properties.first_name} {person.properties.last_name}'}",
                "phone": "{person.properties.phone}",
                "last_seen_at": "{toUnixTimestamp(event.timestamp)}",
            },
            "secret": False,
            "required": False,
        },
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

template_send_event: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    type="destination",
    id="template-intercom-event",
    name="Intercom",
    description="Send events to Intercom",
    icon_url="/static/services/intercom.png",
    category=["Customer Success"],
    hog="""
if (empty(inputs.email)) {
    print('No email set. Skipping...')
    return
}

let regions := {
    'US': 'api.intercom.io',
    'EU': 'api.eu.intercom.io',
    'AU': 'api.au.intercom.io',
}

let user := fetch(f'https://{regions[inputs.oauth['app.region']]}/contacts/search', {
    'method': 'POST',
    'headers': {
        'Content-Type': 'application/json',
        'Intercom-Version': '2.11',
        'Accept': 'application/json',
        'Authorization': f'Bearer {inputs.oauth.access_token}',
    },
    'body': {
        'query': {
            'field': 'email',
            'operator': '=',
            'value': inputs.email
        }
    }
})

let payload := {
    'email': inputs.email
}

if (inputs.include_all_properties) {
    for (let key, value in person.properties) {
        if (not empty(value) and not key like '$%') {
            payload[key] := value
        }
    }
}

for (let key, value in inputs.properties) {
    if (not empty(value)) {
        payload[key] := value
    }
}

let res

if (user.body.total_count == 1) {
    res := fetch(f'https://{regions[inputs.oauth['app.region']]}/contacts/{user.body.data.1.id}', {
        'method': 'PUT',
        'headers': {
            'Content-Type': 'application/json',
            'Intercom-Version': '2.11',
            'Accept': 'application/json',
            'Authorization': f'Bearer {inputs.oauth.access_token}',
        },
        'body': payload
    })
}

if (res.status >= 400) {
    throw Error(f'Error from intercom api (status {res.status}): {res.body}')
} else if (user.status >= 400) {
    throw Error(f'Error from intercom api (status {user.status}): {user.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "oauth",
            "type": "integration",
            "integration": "intercom",
            "label": "Intercom account",
            "requiredScopes": "placeholder",  # intercom scopes are only configurable in the oauth app settings
            "secret": False,
            "required": True,
        },
        {
            "key": "email",
            "type": "string",
            "label": "Email of the user",
            "description": "Where to find the email of the user.",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "eventName",
            "type": "string",
            "label": "Event name",
            "description": "A standard event or custom event name.",
            "default": "{event.event}",
            "secret": False,
            "required": True,
        },
        {
            "key": "eventTime",
            "type": "string",
            "label": "Event time",
            "description": "A Unix timestamp in seconds indicating when the actual event occurred.",
            "default": "{toInt(toUnixTimestamp(event.timestamp))}",
            "secret": False,
            "required": True,
        },
        {
            "key": "include_all_properties",
            "type": "boolean",
            "label": "Include all properties as attributes",
            "description": "If set, all person properties will be included. Individual attributes can be overridden below.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Property mapping",
            "description": "Map of Intercom properties and their values. You can use the filters section to filter out unwanted events.",
            "default": {
                "name": "{f'{person.properties.first_name} {person.properties.last_name}' == ' ' ? null : f'{person.properties.first_name} {person.properties.last_name}'}",
                "phone": "{person.properties.phone}",
                "last_seen_at": "{toUnixTimestamp(event.timestamp)}",
            },
            "secret": False,
            "required": False,
        },
    ],
    filters={
        "events": [
            {"id": "$pageview", "name": "$pageview", "type": "events", "order": 0},
        ],
        "actions": [],
        "filter_test_accounts": True,
    },
)


class TemplateIntercomMigrator(HogFunctionTemplateMigrator):
    plugin_url = "https://github.com/PostHog/posthog-intercom-plugin"

    @classmethod
    def migrate(cls, obj):
        hf = deepcopy(dataclasses.asdict(template))

        useEuropeanDataStorage = obj.config.get("useEuropeanDataStorage", "No")
        intercomApiKey = obj.config.get("intercomApiKey", "")
        triggeringEvents = obj.config.get("triggeringEvents", "$identify")
        ignoredEmailDomains = obj.config.get("ignoredEmailDomains", "")

        hf["filters"] = {}

        events_to_filter = [event.strip() for event in triggeringEvents.split(",") if event.strip()]
        domains_to_filter = [domain.strip() for domain in ignoredEmailDomains.split(",") if domain.strip()]

        if domains_to_filter:
            hf["filters"]["properties"] = [
                {
                    "key": "email",
                    "value": domain,
                    "operator": "not_icontains",
                    "type": "person",
                }
                for domain in domains_to_filter
            ]

        if events_to_filter:
            hf["filters"]["events"] = [
                {"id": event, "name": event, "type": "events", "order": 0} for event in events_to_filter
            ]

        hf["inputs"] = {
            "access_token": {"value": intercomApiKey},
            "host": {"value": "api.eu.intercom.com"}
            if useEuropeanDataStorage == "Yes"
            else {"value": "api.intercom.io"},
            "email": {"value": "{person.properties.email}"},
        }

        return hf
