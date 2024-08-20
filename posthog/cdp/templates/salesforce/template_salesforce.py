from posthog.cdp.templates.hog_function_template import HogFunctionTemplate

common_filters = {
    "events": [{"id": "$identify", "name": "$identify", "type": "events", "order": 0}],
    "actions": [],
    "filter_test_accounts": True,
}

common_inputs = {
    "oauth": {
        "key": "oauth",
        "type": "integration",
        "integration": "salesforce",
        "label": "Salesforce account",
        "secret": False,
        "required": True,
    }
}

template_create: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    id="template-salesforce-create",
    name="Create Salesforce objects",
    description="Create objects in Salesforce",
    icon_url="/static/services/salesforce.png",
    hog="""
let res := fetch(f'{inputs.oauth.instance_url}/services/data/v61.0/sobjects/{inputs.path}', {
  'body': inputs.properties,
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.oauth.access_token}',
    'Content-Type': 'application/json'
  }
});

if (res.status >= 400) {
  print('Bad response:', res.status, res.body)
}
""".strip(),
    inputs_schema=[
        common_inputs["oauth"],
        {
            "key": "path",
            "type": "string",
            "label": "Object path",
            "description": "The path to the object you want to create.",
            "default": "Contact",
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Property mapping",
            "description": "Map of properties for the Salesforce Object. These should exist",
            "default": {
                "Email": "{person.properties.email}",
                "LastName": "{person.properties.lastname}",
                "FirstName": "{person.properties.firstname}",
            },
            "secret": False,
            "required": True,
        },
    ],
    filters=common_filters,
)

template_update: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    id="template-salesforce-update",
    name="Update Salesforce objects",
    description="Update objects in Salesforce",
    icon_url="/static/services/salesforce.png",
    hog="""
let res := fetch(f'{inputs.oauth.instance_url}/services/data/v61.0/sobjects/{inputs.path}', {
  'body': inputs.properties,
  'method': 'PATCH',
  'headers': {
    'Authorization': f'Bearer {inputs.oauth.access_token}',
    'Content-Type': 'application/json'
  }
});

if (res.status >= 400) {
  print('Bad response:', res.status, res.body)
}
""".strip(),
    inputs_schema=[
        common_inputs["oauth"],
        {
            "key": "path",
            "type": "string",
            "label": "Object path",
            "description": "The path to the object you want to create or update. This can be a standard object like 'Contact' for creating records or `Lead/Email/{person.properties.email}` for updating a lead by email. See https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/dome_upsert.htm for more information.",
            "default": "Leads/Email/{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Property mapping",
            "description": "Map of properties for the Salesforce Object.",
            "default": {
                "City": "{event.properties.$geoip_city_name}",
                "State": "{event.properties.$geoip_subdivison_1_name}",
                "Country": "{event.properties.$geoip_country_name}",
                "Latitude": "{event.properties.$geoip_latitude}",
                "Longitude": "{event.properties.$geoip_longitude}",
            },
            "secret": False,
            "required": True,
        },
    ],
    filters=common_filters,
)
