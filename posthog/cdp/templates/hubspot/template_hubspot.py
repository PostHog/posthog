import dataclasses
from copy import deepcopy

from posthog.cdp.templates.hog_function_template import HogFunctionTemplate, HogFunctionTemplateMigrator


template: HogFunctionTemplate = HogFunctionTemplate(
    status="stable",
    free=False,
    type="destination",
    id="template-hubspot",
    name="Hubspot",
    description="Creates a new contact in Hubspot whenever an event is triggered.",
    icon_url="/static/services/hubspot.png",
    category=["CRM", "Customer Success"],
    hog="""
let properties := {
    'email': inputs.email
}
for (let key, value in inputs.properties) {
    if (typeof(value) in ('object', 'array', 'tuple')) {
        properties[key] := jsonStringify(value)
    } else {
        properties[key] := value
    }
}

if (empty(properties.email)) {
    print('`email` input is empty. Not creating a contact.')
    return
}

let headers := {
    'Authorization': f'Bearer {inputs.oauth.access_token}',
    'Content-Type': 'application/json'
}
let body := {
    'inputs': [
        {
            'properties': properties,
            'id': properties.email,
            'idProperty': 'email'
        }
    ]
}

let res := fetch('https://api.hubapi.com/crm/v3/objects/contacts/batch/upsert', {
    'method': 'POST',
    'headers': headers,
    'body': body
})

if (res.status == 200) {
    print(f'Contact {properties.email} updated successfully!')
} else {
    throw Error(f'Error updating contact {properties.email} (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "oauth",
            "type": "integration",
            "integration": "hubspot",
            "label": "Hubspot connection",
            "requiredScopes": "crm.objects.contacts.write crm.objects.contacts.read",
            "secret": False,
            "required": True,
        },
        {
            "key": "email",
            "type": "string",
            "label": "Email of the user",
            "description": "Where to find the email for the contact to be created. You can use the filters section to filter out unwanted emails or internal users.",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Property mapping",
            "description": "Map any event properties to Hubspot properties.",
            "default": {
                "firstname": "{person.properties.firstname}",
                "lastname": "{person.properties.lastname}",
                "company": "{person.properties.company}",
                "phone": "{person.properties.phone}",
                "website": "{person.properties.website}",
            },
            "secret": False,
            "required": True,
        },
    ],
    filters={
        "events": [{"id": "$identify", "name": "$identify", "type": "events", "order": 0}],
        "actions": [],
        "filter_test_accounts": True,
    },
)

template_event: HogFunctionTemplate = HogFunctionTemplate(
    status="stable",
    free=False,
    id="template-hubspot-event",
    type="destination",
    name="Hubspot",
    description="Send events to Hubspot.",
    icon_url="/static/services/hubspot.png",
    category=["CRM", "Customer Success"],
    hog="""
if (empty(inputs.email)) {
    print('`email` input is empty. Not sending event.')
    return
}

let eventName := replaceAll(replaceAll(trim(lower(inputs.eventName)), '$', ''), ' ', '_')

if (not match(eventName, '^[a-z][a-z0-9_-]*$')) {
    throw Error(f'Event name must start with a letter and can only contain lowercase letters, numbers, underscores, and hyphens. Not sending event...')
}

let properties := {}

for (let key, value in inputs.properties) {
    if (not empty(value)) {
        if (typeof(value) in ('object', 'array', 'tuple')) {
            properties[key] := jsonStringify(value)
        } else {
            properties[key] := value
        }
    }
}

if (inputs.include_all_properties) {
    for (let key, value in event.properties) {
        if (not empty(value) and not key like '$%') {
            if (typeof(value) in ('object', 'array', 'tuple')) {
                properties[key] := jsonStringify(value)
            } else {
                properties[key] := value
            }
        }
    }
}

let eventSchema := fetch(f'https://api.hubapi.com/events/v3/event-definitions/{eventName}/?includeProperties=true', {
    'method': 'GET',
    'headers': {
        'Authorization': f'Bearer {inputs.oauth.access_token}',
        'Content-Type': 'application/json'
    },
})

fun getPropValueType(propValue) {
    let propType := typeof(propValue)
    if (propType == 'string') {
        if (match(propValue, '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}.[0-9]{3}Z$')) {
            return 'datetime'
        }
        return 'string'
    } else if (propType == 'integer') {
        return 'number'
    } else if (propType == 'float') {
        return 'number'
    } else if (propType == 'boolean') {
        return 'enumeration'
    } else if (propType == 'object') {
        return 'string'
    } else {
        return null
    }
}

fun getPropValueTypeDefinition(name, propValue) {
    let propType := typeof(propValue)
    if (propType == 'string' or propType == 'object' or propType == 'array' or propType == 'tuple') {
        if (match(propValue, '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}.[0-9]{3}Z$')) {
            return {
                'name': name,
                'label': name,
                'type': 'datetime',
                'description': f'{name} - (created by PostHog)'
            }
        }
        return {
            'name': name,
            'label': name,
            'type': 'string',
            'description': f'{name} - (created by PostHog)'
        }
    } else if (propType == 'integer' or propType == 'float') {
        return {
            'name': name,
            'label': name,
            'type': 'number',
            'description': f'{name} - (created by PostHog)'
        }
    } else if (propType == 'boolean') {
        return {
            'name': name,
            'label': name,
            'type': 'enumeration',
            'description': f'{name} - (created by PostHog)',
            'options': [
                {
                    'label': 'true',
                    'value': true,
                    'hidden': false,
                    'description': 'True',
                    'displayOrder': 1
                },
                {
                    'label': 'false',
                    'value': false,
                    'hidden': false,
                    'description': 'False',
                    'displayOrder': 2
                }
            ]
        }
    } else {
        print('unsupported type for key', name)
        return null
    }
}

let fullyQualifiedName := ''

if (eventSchema.status >= 400) {
    let body := {
        'label': eventName,
        'name': eventName,
        'description': f'{eventName} - (created by PostHog)',
        'primaryObject': 'CONTACT',
        'propertyDefinitions': []
    }

    for (let key, value in properties) {
        body.propertyDefinitions := arrayPushBack(body.propertyDefinitions, getPropValueTypeDefinition(key, value))
    }

    let res := fetch('https://api.hubapi.com/events/v3/event-definitions', {
        'method': 'POST',
        'headers': {
            'Authorization': f'Bearer {inputs.oauth.access_token}',
            'Content-Type': 'application/json'
        },
        'body': body
    })

    if (res.status >= 400) {
        throw Error(f'Error from api.hubapi.com api: {res.status}: {res.body}');
    } else {
        fullyQualifiedName := res.body.fullyQualifiedName
    }
} else {
    fullyQualifiedName := eventSchema.body.fullyQualifiedName
    let missingProperties := []
    let wrongTypeProperties := []
    for (let key, value in properties) {
        if (not arrayExists(property -> property.name == key, eventSchema.body.properties)) {
            missingProperties := arrayPushBack(missingProperties, { 'key': key, 'value': value })
        } else if (not arrayExists(property -> property.name == key and property.type == getPropValueType(value), eventSchema.body.properties)) {
            wrongTypeProperties := arrayPushBack(wrongTypeProperties, { 'key': key, 'value': value })
        }
    }

    if (not empty(missingProperties)) {
        for (let i, obj in missingProperties) {
            let res := fetch(f'https://api.hubapi.com/events/v3/event-definitions/{eventName}/property', {
                'method': 'POST',
                'headers': {
                    'Authorization': f'Bearer {inputs.oauth.access_token}',
                    'Content-Type': 'application/json'
                },
                'body': getPropValueTypeDefinition(obj.key, obj.value)
            })

            if (res.status >= 400) {
                throw Error(f'Error from api.hubapi.com api: {res.status}: {res.body}');
            }
        }
    }

    if (not empty(wrongTypeProperties)) {
        throw Error(f'Property type mismatch for the following properties: {wrongTypeProperties}. Not sending event.')
    }
}

let res := fetch('https://api.hubapi.com/events/v3/send', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Bearer {inputs.oauth.access_token}',
        'Content-Type': 'application/json'
    },
    'body': {
        'eventName': fullyQualifiedName,
        'email': inputs.email,
        'occurredAt': event.timestamp,
        'properties': properties
    }
})

if (res.status >= 400) {
    throw Error(f'Error from api.hubapi.com api: {res.status}: {res.body}');
}
""".strip(),
    inputs_schema=[
        {
            "key": "oauth",
            "type": "integration",
            "integration": "hubspot",
            "label": "Hubspot connection",
            "requiredScopes": "analytics.behavioral_events.send behavioral_events.event_definitions.read_write",
            "secret": False,
            "required": True,
        },
        {
            "key": "eventName",
            "type": "string",
            "label": "Event Name",
            "description": "Hubspot only allows events that start with a letter and can only contain lowercase letters, numbers, underscores, and hyphens. Whitespace will be automatically replaced with _",
            "default": "{event.event}",
            "secret": False,
            "required": True,
        },
        {
            "key": "email",
            "type": "string",
            "label": "Email of the user",
            "description": "Where to find the email for the contact to be created. You can use the filters section to filter out unwanted emails or internal users.",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "include_all_properties",
            "type": "boolean",
            "label": "Include all event properties",
            "description": "If set, all event properties will be included. Individual properties can be overridden below.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Property mapping",
            "description": "Map any event properties to Hubspot properties.",
            "default": {
                "price": "{event.properties.price}",
                "currency": "USD",
            },
            "secret": False,
            "required": True,
        },
    ],
    filters={
        "events": [{"id": "checkout", "name": "checkout", "type": "events", "order": 0}],
        "actions": [],
        "filter_test_accounts": True,
    },
)


class TemplateHubspotMigrator(HogFunctionTemplateMigrator):
    plugin_url = "https://github.com/PostHog/hubspot-plugin"

    @classmethod
    def migrate(cls, obj):
        hf = deepcopy(dataclasses.asdict(template))

        # Must reauthenticate with HubSpot
        hubspotAccessToken = obj.config.get("hubspotAccessToken", "")
        triggeringEvents = [x.strip() for x in obj.config.get("triggeringEvents", "").split(",") if x]
        additionalPropertyMappings = [
            x.strip() for x in obj.config.get("additionalPropertyMappings", "").split(",") if x
        ]
        ignoredEmails = [x.strip() for x in obj.config.get("ignoredEmails", "").split(",") if x]

        hf["inputs_schema"][0] = {
            "key": "access_token",
            "type": "string",
            "label": "Hubspot authorization token",
            "secret": True,
            "required": True,
        }
        hf["hog"] = hf["hog"].replace("inputs.oauth.access_token", "inputs.access_token")

        hf["inputs"] = {
            "access_token": {"value": hubspotAccessToken},
            "email": {"value": "{person.properties.email}"},
            "properties": {
                "value": {
                    "firstname": "{person.properties.firstname ?? person.properties.firstName ?? person.properties.first_name}",
                    "lastname": "{person.properties.lastname ?? person.properties.lastName ?? person.properties.last_name}",
                    "company": "{person.properties.company ?? person.properties.companyName ?? person.properties.company_name}",
                    "phone": "{person.properties.phone ?? person.properties.phoneNumber ?? person.properties.phone_number}",
                    "website": "{person.properties.website ?? person.properties.companyWebsite ?? person.properties.company_website}",
                }
            },
        }
        for mapping in additionalPropertyMappings:
            personPropertyName, hubSpotPropertyName = mapping.split(":")
            hf["inputs"]["properties"]["value"][hubSpotPropertyName] = f"{{person.properties.{personPropertyName}}}"

        hf["filters"] = {}

        if ignoredEmails:
            hf["filters"]["properties"] = [
                {
                    "key": "email",
                    "value": domain,
                    "operator": "not_icontains",
                    "type": "person",
                }
                for domain in ignoredEmails
            ]

        if triggeringEvents:
            hf["filters"]["events"] = [
                {
                    "id": event,
                    "name": event,
                    "type": "events",
                    "properties": [],
                }
                for event in triggeringEvents
            ]

        return hf
