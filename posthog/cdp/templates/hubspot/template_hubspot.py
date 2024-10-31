import dataclasses
from copy import deepcopy

from posthog.cdp.templates.hog_function_template import HogFunctionTemplate, HogFunctionTemplateMigrator


template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
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
