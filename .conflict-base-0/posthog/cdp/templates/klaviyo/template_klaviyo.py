from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template_user: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="stable",
    free=False,
    type="destination",
    id="template-klaviyo-user",
    name="Klaviyo",
    description="Updates a contact in Klaviyo",
    icon_url="/static/services/klaviyo.png",
    category=["Email Marketing"],
    code_language="hog",
    code="""
if (empty(inputs.externalId) and empty(inputs.email)) {
    print('Email or External ID has to be set. Skipping...')
    return
}

let body := {
    'data': {
        'type': 'profile',
        'attributes': {
            'location': {},
            'properties': {},
        }
    }
}

if (not empty(person.properties.$geoip_latitude)) body.data.attributes.location.latitude := person.properties.$geoip_latitude
if (not empty(person.properties.$geoip_longitude)) body.data.attributes.location.longitude := person.properties.$geoip_longitude
if (not empty(person.properties.$geoip_city_name)) body.data.attributes.location.city := person.properties.$geoip_city_name
if (not empty(person.properties.$geoip_country_name)) body.data.attributes.location.country := person.properties.$geoip_country_name
if (not empty(person.properties.$geoip_continent_code)) body.data.attributes.location.region := person.properties.$geoip_continent_code
if (not empty(person.properties.$geoip_postal_code)) body.data.attributes.location.zip := person.properties.$geoip_postal_code
if (not empty(person.properties.$geoip_time_zone)) body.data.attributes.location.timezone := person.properties.$geoip_time_zone

if (not empty(inputs.email)) body.data.attributes.email := inputs.email
if (not empty(inputs.externalId)) body.data.attributes.external_id := inputs.externalId

if (inputs.include_all_properties) {
    for (let key, value in person.properties) {
        if (not empty(value) and not key like '$%') {
            body.data.attributes.properties[key] := value
        }
    }
}

for (let key, value in inputs.customProperties) {
    if (not empty(value)) {
        body.data.attributes.properties[key] := value
    }
}

let res := fetch('https://a.klaviyo.com/api/profiles', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Klaviyo-API-Key {inputs.apiKey}',
        'revision': '2024-10-15',
        'Content-Type': 'application/json'
    },
    'body': body
})

if (res.status == 409 and not empty(res.body.errors.1.meta.duplicate_profile_id)) {
    let id := res.body.errors.1.meta.duplicate_profile_id
    body.data.id := id

    let res2 := fetch(f'https://a.klaviyo.com/api/profiles/{id}', {
        'method': 'PATCH',
        'headers': {
            'Authorization': f'Klaviyo-API-Key {inputs.apiKey}',
            'revision': '2024-10-15',
            'Content-Type': 'application/json'
        },
        'body': body
    })
    if (res2.status >= 400) {
        throw Error(f'Error from a.klaviyo.com api: {res2.status}: {res2.body}');
    }
} else if (res.status >= 400) {
    throw Error(f'Error from a.klaviyo.com api: {res.status}: {res.body}');
}

""".strip(),
    inputs_schema=[
        {
            "key": "apiKey",
            "type": "string",
            "label": "Klaviyo Private API Key",
            "description": "You can create a Private API Key in the account settings (https://www.klaviyo.com/settings/account/api-keys)",
            "secret": True,
            "required": True,
        },
        {
            "key": "email",
            "type": "string",
            "label": "User Email",
            "description": "Where to find the email for the contact to be created. You can use the filters section to filter out unwanted emails or internal users.",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "externalId",
            "type": "string",
            "label": "External ID",
            "description": "A unique identifier used to associate Klaviyo profiles with profiles in an external system",
            "default": "{person.id}",
            "secret": False,
            "required": True,
        },
        {
            "key": "include_all_properties",
            "type": "boolean",
            "label": "Include all person properties as custom properties",
            "description": "If set, all event properties will be included as attributes. Individual attributes can be overridden below. For identify events the Person properties will be used.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "customProperties",
            "type": "dictionary",
            "label": "Custom properties",
            "description": "Map of Custom properties and their values.",
            "default": {
                "first_name": "{person.properties.firstname}",
                "last_name": "{person.properties.lastname}",
                "title": "{person.properties.title}",
                "organization": "{person.properties.organization}",
                "phone_number": "{person.properties.phone}",
            },
            "secret": False,
            "required": False,
        },
    ],
    filters={
        "events": [
            {"id": "$identify", "name": "$identify", "type": "events", "order": 0},
            {"id": "$set", "name": "$set", "type": "events", "order": 0},
        ],
        "actions": [],
        "filter_test_accounts": True,
    },
)

template_event: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="stable",
    free=False,
    type="destination",
    id="template-klaviyo-event",
    name="Klaviyo",
    description="Send events to Klaviyo",
    icon_url="/static/services/klaviyo.png",
    category=["Email Marketing"],
    code_language="hog",
    code="""
if (empty(inputs.externalId) and empty(inputs.email)) {
    print('Email or External ID has to be set. Skipping...')
    return
}

let body := {
    'data': {
        'type': 'event',
        'attributes': {
            'properties': {},
            'metric': {
                'data': {
                    'type': 'metric',
                    'attributes': {
                        'name': event.event
                    }
                }
            },
            'profile': {
                'data': {
                    'type': 'profile',
                    'attributes': {}
                }
            }
        }
    }
}

if (not empty(inputs.email)) body.data.attributes.profile.data.attributes.email := inputs.email
if (not empty(inputs.externalId)) body.data.attributes.profile.data.attributes.external_id := inputs.externalId

if (inputs.include_all_properties) {
    for (let key, value in event.properties) {
        if (not empty(value) and not key like '$%') {
            body.data.attributes.properties[key] := value
        }
    }
}

for (let key, value in inputs.attributes) {
    if (not empty(value)) {
        body.data.attributes.properties[key] := value
    }
}

let res := fetch('https://a.klaviyo.com/api/events', {
    'method': 'POST',
    'headers': {
        'Authorization': f'Klaviyo-API-Key {inputs.apiKey}',
        'revision': '2024-10-15',
        'Content-Type': 'application/json'
    },
    'body': body
})


if (res.status >= 400) {
    throw Error(f'Error from a.klaviyo.com api: {res.status}: {res.body}');
}

""".strip(),
    inputs_schema=[
        {
            "key": "apiKey",
            "type": "string",
            "label": "Klaviyo Private API Key",
            "description": "You can create a Private API Key in the account settings (https://www.klaviyo.com/settings/account/api-keys)",
            "secret": True,
            "required": True,
        },
        {
            "key": "email",
            "type": "string",
            "label": "User Email",
            "description": "Where to find the email for the contact to be created. You can use the filters section to filter out unwanted emails or internal users.",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "externalId",
            "type": "string",
            "label": "External ID",
            "description": "A unique identifier used to associate Klaviyo profiles with profiles in an external system",
            "default": "{person.id}",
            "secret": False,
            "required": True,
        },
        {
            "key": "include_all_properties",
            "type": "boolean",
            "label": "Include all event properties as event attributes",
            "description": "If set, all event properties will be included as attributes. Individual attributes can be overridden below.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "attributes",
            "type": "dictionary",
            "label": "Attributes",
            "description": "Map of event attributes and their values.",
            "default": {"price": "{event.properties.price}", "currency": "{event.properties.currency}"},
            "secret": False,
            "required": False,
        },
    ],
    filters={
        "events": [],
        "actions": [],
        "filter_test_accounts": True,
    },
)
