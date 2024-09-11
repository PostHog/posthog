from copy import deepcopy
import dataclasses
from posthog.cdp.templates.hog_function_template import HogFunctionTemplate, HogFunctionTemplateMigrator


template: HogFunctionTemplate = HogFunctionTemplate(
    status="beta",
    id="template-Intercom",
    name="Send data to Intercom",
    description="Send events and contact information to Intercom",
    icon_url="/static/services/intercom.png",
    hog="""
if (empty(inputs.email)) {
    print('`email` input is empty. Skipping.')
    return
}

let res := fetch(f'https://{inputs.host}/events', {
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.access_token}',
    'Content-Type': 'application/json',
    'Accept': 'application/json'
  },
  'body': {
    'event_name': event.name,
    'created_at': toInt(toUnixTimestamp(toDateTime(event.timestamp))),
    'email': inputs.email,
    'id': event.distinct_id,
  }
})

if (res.status >= 200 and res.status < 300) {
    print('Event sent successfully!')
    return
}

if (res.status == 404) {
    print('No existing contact found for email')
    return
}

print('Error sending event:', res.status, res.body)

""".strip(),
    inputs_schema=[
        {
            "key": "access_token",
            "type": "string",
            "label": "Intercom access token",
            "description": "Create an Intercom app (https://developers.intercom.com/docs/build-an-integration/learn-more/authentication), then go to Configure > Authentication to find your token.",
            "secret": True,
            "required": True,
        },
        {
            "key": "host",
            "type": "choice",
            "choices": [
                {
                    "label": "US (api.intercom.io)",
                    "value": "api.intercom.io",
                },
                {
                    "label": "EU (api.eu.intercom.com)",
                    "value": "api.eu.intercom.com",
                },
            ],
            "label": "Data region",
            "description": "Use the EU variant if your Intercom account is based in the EU region",
            "default": "api.intercom.io",
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
    ],
    filters={
        "events": [{"id": "$identify", "name": "$identify", "type": "events", "order": 0}],
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
