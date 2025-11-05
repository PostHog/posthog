import dataclasses
from copy import deepcopy

from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC, HogFunctionTemplateMigrator

# Based off of https://www.twilio.com/docs/sendgrid/api-reference/contacts/add-or-update-a-contact

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-sendgrid",
    name="Sendgrid",
    description="Update marketing contacts in Sendgrid",
    icon_url="/static/services/sendgrid.png",
    category=["Email Marketing"],
    code_language="hog",
    code="""
if (empty(inputs.email)) {
    print('`email` input is empty. Not updating contacts.')
    return
}

let contact := {
  'email': inputs.email,
}

for (let key, value in inputs.properties) {
    if (not empty(value)) {
        contact[key] := value
    }
}

let headers :=  {
    'Authorization': f'Bearer {inputs.api_key}',
    'Content-Type': 'application/json'
}

if (not empty(inputs.custom_fields)) {
    let response := fetch('https://api.sendgrid.com/v3/marketing/field_definitions', {
        'method': 'GET',
        'headers': headers
    })
    if (response.status != 200) {
        throw Error(f'Could not fetch custom fields. Status: {response.status}')
    }
    contact['custom_fields'] := {}
    for (let obj in response.body?.custom_fields ?? {}) {
        let inputValue := inputs.custom_fields[obj.name]
        if (not empty(inputValue)) {
            contact['custom_fields'][obj.id] := inputValue
        }
    }
}

let res := fetch('https://api.sendgrid.com/v3/marketing/contacts', {
    'method': 'PUT',
    'headers': headers,
    'body': { 'contacts': [contact] }
})

if (res.status > 300) {
    throw Error(f'Error from api.sendgrid.com (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "api_key",
            "type": "string",
            "label": "Sendgrid API Key",
            "description": "See https://app.sendgrid.com/settings/api_keys",
            "secret": True,
            "required": True,
        },
        {
            "key": "email",
            "type": "string",
            "label": "The email of the user",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "dictionary",
            "label": "Reserved fields",
            "description": "The following field names are allowed: address_line_1, address_line_2, alternate_emails, anonymous_id, city, country, email, external_id, facebook, first_name, last_name, phone_number_id, postal_code, state_province_region, unique_name, whatsapp.",
            "default": {
                "first_name": "{person.properties.first_name}",
                "last_name": "{person.properties.last_name}",
                "city": "{person.properties.city}",
                "country": "{person.properties.country}",
                "postal_code": "{person.properties.postal_code}",
            },
            "secret": False,
            "required": True,
        },
        {
            "key": "custom_fields",
            "type": "dictionary",
            "label": "Custom fields",
            "description": "Configure custom fields in SendGrid before using them here: https://mc.sendgrid.com/custom-fields",
            "default": {},
            "secret": False,
            "required": False,
        },
    ],
    filters={
        "events": [{"id": "$identify", "name": "$identify", "type": "events", "order": 0}],
        "actions": [],
        "filter_test_accounts": True,
    },
)


class TemplateSendGridMigrator(HogFunctionTemplateMigrator):
    plugin_url = "https://github.com/PostHog/sendgrid-plugin"

    @classmethod
    def migrate(cls, obj):
        hf = deepcopy(dataclasses.asdict(template))
        hf["hog"] = hf["code"]
        del hf["code"]

        sendgridApiKey = obj.config.get("sendgridApiKey", "")
        customFields = obj.config.get("customFields", "")
        sendgrid_fields = [
            "address_line_1",
            "address_line_2",
            "alternate_emails",
            "anonymous_id",
            "city",
            "country",
            "email",
            "external_id",
            "facebook",
            "first_name",
            "last_name",
            "phone_number_id",
            "postal_code",
            "state_province_region",
            "unique_name",
            "whatsapp",
        ]

        hf["filters"] = {}
        hf["filters"]["events"] = [{"id": "$identify", "name": "$identify", "type": "events", "order": 0}]

        hf["inputs"] = {
            "api_key": {"value": sendgridApiKey},
            "email": {"value": "{person.properties.email}"},
            "properties": {"value": {}},
            "custom_fields": {"value": {}},
        }
        if customFields:
            for field in customFields.split(","):
                if "=" in field:
                    posthog_prop, sendgrid_field = field.split("=")
                else:
                    posthog_prop = sendgrid_field = field.strip()
                posthog_prop = f"{{person.properties.{posthog_prop}}}"
                if sendgrid_field in sendgrid_fields:
                    hf["inputs"]["properties"]["value"][sendgrid_field] = posthog_prop
                else:
                    hf["inputs"]["custom_fields"]["value"][sendgrid_field] = posthog_prop

        return hf
