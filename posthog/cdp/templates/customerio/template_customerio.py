import dataclasses
from copy import deepcopy

from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC, HogFunctionTemplateMigrator

# Based off of https://customer.io/docs/api/track/#operation/entity

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="stable",
    free=False,
    type="destination",
    id="template-customerio",
    name="Customer.io",
    description="Identify or track events against customers in Customer.io",
    icon_url="/static/services/customerio.png",
    category=["Email Marketing"],
    code_language="hog",
    code="""
let action := inputs.action
let name := event.event


if (empty(inputs.identifier_value) or empty(inputs.identifier_key)) {
    print('No identifier set. Skipping as identifier is required.')
    return
}

let identifiers := {
    inputs.identifier_key: inputs.identifier_value
}

if (action == 'automatic') {
    if (event.event in ('$identify', '$set')) {
        action := 'identify'
        name := null
    } else if (event.event == '$pageview') {
        action := 'page'
        name := event.properties.$current_url
    } else if (event.event == '$screen') {
        action := 'screen'
        name := event.properties.$screen_name
    } else {
        action := 'event'
    }
}

let attributes := inputs.include_all_properties ? action == 'identify' ? person.properties : event.properties : {}
if (inputs.include_all_properties and action != 'identify' and not empty(event.elements_chain)) {
    attributes['$elements_chain'] := event.elements_chain
}
let timestamp := toInt(toUnixTimestamp(toDateTime(event.timestamp)))

for (let key, value in inputs.attributes) {
    attributes[key] := value
}

for (let key, value in attributes) {
    if (value and typeof(value) == 'string') {
        if (length(value) > 1000) {
            attributes[key] := substring(value, 1, 1000)
        }
    }
}

let res := fetch(f'https://{inputs.host}/api/v2/entity', {
    'method': 'POST',
    'headers': {
        'User-Agent': 'PostHog Customer.io App',
        'Authorization': f'Basic {base64Encode(f'{inputs.site_id}:{inputs.token}')}',
        'Content-Type': 'application/json'
    },
    'body': {
        'type': 'person',
        'action': action,
        'name': name,
        'identifiers': identifiers,
        'attributes': attributes,
        'timestamp': timestamp
    }
})

if (res.status >= 400) {
    throw Error(f'Error from customer.io api: {res.status}: {res.body}');
}

""".strip(),
    inputs_schema=[
        {
            "key": "site_id",
            "type": "string",
            "label": "Customer.io site ID",
            "secret": False,
            "required": True,
        },
        {
            "key": "token",
            "type": "string",
            "label": "Customer.io API Key",
            "description": "You can find your API key in your Customer.io account settings (https://fly.customer.io/settings/api_credentials)",
            "secret": True,
            "required": True,
        },
        {
            "key": "host",
            "type": "choice",
            "choices": [
                {
                    "label": "US (track.customer.io)",
                    "value": "track.customer.io",
                },
                {
                    "label": "EU (track-eu.customer.io)",
                    "value": "track-eu.customer.io",
                },
            ],
            "label": "Customer.io region",
            "description": "Use the EU variant if your Customer.io account is based in the EU region",
            "default": "track.customer.io",
            "secret": False,
            "required": True,
        },
        {
            "key": "identifier_key",
            "type": "choice",
            "label": "Identifier key",
            "description": "The kind of identifier to be used. See here for more information: https://customer.io/docs/api/track/#operation/entity",
            "default": "email",
            "choices": [
                {
                    "label": "Email",
                    "value": "email",
                },
                {
                    "label": "ID",
                    "value": "id",
                },
                {
                    "label": "Customer.io ID",
                    "value": "cio_id",
                },
            ],
            "secret": False,
            "required": True,
        },
        {
            "key": "identifier_value",
            "type": "string",
            "label": "Identifier value",
            "description": "The value to be used for the identifier. If the value is empty nothing will be sent. See here for more information: https://customer.io/docs/api/track/#operation/entity",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "action",
            "type": "choice",
            "label": "Action",
            "description": "Choose the action to be tracked. Automatic will convert $identify, $pageview and $screen to identify, page and screen automatically - otherwise defaulting to event",
            "default": "automatic",
            "choices": [
                {
                    "label": "Automatic",
                    "value": "automatic",
                },
                {
                    "label": "Identify",
                    "value": "identify",
                },
                {
                    "label": "Event",
                    "value": "event",
                },
                {
                    "label": "Page",
                    "value": "page",
                },
                {
                    "label": "Screen",
                    "value": "screen",
                },
                {
                    "label": "Delete",
                    "value": "delete",
                },
            ],
            "secret": False,
            "required": True,
        },
        {
            "key": "include_all_properties",
            "type": "boolean",
            "label": "Include all properties as attributes",
            "description": "If set, all event properties will be included as attributes. Individual attributes can be overridden below. For identify events the Person properties will be used.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "attributes",
            "type": "dictionary",
            "label": "Attribute mapping",
            "description": "Map of Customer.io attributes and their values. You can use the filters section to filter out unwanted events.",
            "default": {
                "email": "{person.properties.email}",
                "lastname": "{person.properties.lastname}",
                "firstname": "{person.properties.firstname}",
            },
            "secret": False,
            "required": False,
        },
    ],
    filters={
        "events": [
            {"id": "$identify", "name": "$identify", "type": "events", "order": 0},
            {"id": "$pageview", "name": "$pageview", "type": "events", "order": 0},
        ],
        "actions": [],
        "filter_test_accounts": True,
    },
)


class TemplateCustomerioMigrator(HogFunctionTemplateMigrator):
    plugin_url = "https://github.com/PostHog/customerio-plugin"

    @classmethod
    def migrate(cls, obj):
        hf = deepcopy(dataclasses.asdict(template))
        hf["hog"] = hf["code"]
        del hf["code"]

        host = obj.config.get("host", "track.customer.io")
        events_to_send = obj.config.get("eventsToSend")
        token = obj.config.get("customerioToken", "")
        customerio_site_id = obj.config.get("customerioSiteId", "")
        anon_option = obj.config.get("sendEventsFromAnonymousUsers", "Send all events")
        identify_by_email = obj.config.get("identifyByEmail", "No") == "Yes"

        hf["filters"] = {}

        if anon_option == "Send all events":
            pass
        elif anon_option == "Only send events from users with emails":
            # TODO: Add support for general filters
            hf["filters"]["properties"] = [
                {
                    "key": "email",
                    "value": "is_set",
                    "operator": "is_set",
                    "type": "person",
                }
            ]
        elif anon_option == "Only send events from users that have been identified":
            hf["filters"]["properties"] = [
                {
                    "key": "$is_identified",
                    "value": ["true"],
                    "operator": "exact",
                    "type": "event",
                }
            ]

        if events_to_send:
            hf["filters"]["events"] = [
                {"id": event.strip(), "name": event.strip() or "All events", "type": "events", "order": 0}
                for event in events_to_send.split(",")
            ]

        hf["inputs"] = {
            "action": {"value": "automatic"},
            "site_id": {"value": customerio_site_id},
            "token": {"value": token},
            "host": {"value": host},
            "identifier_key": {"value": "email" if identify_by_email else "id"},
            "identifier_value": {"value": "{person.properties.email}" if identify_by_email else "{event.distinct_id}"},
            "include_all_properties": {"value": True},
            "attributes": {"value": {}},
        }

        return hf
