import dataclasses
from copy import deepcopy

from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC, HogFunctionTemplateMigrator

common_filters = {
    "events": [{"id": "$identify", "name": "$identify", "type": "events", "order": 0}],
    "actions": [],
    "filter_test_accounts": True,
}

# Salesforce answers every rejection with a 4xx, so the status alone can't tell an expired session apart from a
# missing object permission or an over-long field. The errorCode in the body is what distinguishes them.
error_handling_hog = """
let salesforceError := (res) -> {
  let code := ''
  let message := ''
  if (typeof(res.body) in ('array', 'tuple') and typeof(res.body.1) == 'object') {
    code := res.body.1.errorCode ?? ''
    message := res.body.1.message ?? ''
  } else if (typeof(res.body) == 'object') {
    code := res.body.errorCode ?? ''
    message := res.body.message ?? ''
  }
  let detail := code != '' ? f'{code}: {message}' : f'{res.body}'

  if (code in ('INVALID_SESSION_ID', 'INVALID_AUTH_HEADER', 'INVALID_LOGIN') or (res.status == 401 and code == '')) {
    return f'Salesforce rejected the credentials (status {res.status}, {detail}). Reconnect the Salesforce account for this destination.'
  }
  if (res.status == 405 or code == 'METHOD_NOT_ALLOWED') {
    return f'Salesforce rejected the request because the object path points at a collection, not a single record (status {res.status}, {detail}). To update a record, set the object path to Object/ExternalIdField/value, for example Lead/Email/jane@example.com. Make sure the external ID field and its value are both present.'
  }
  if (res.status >= 400 and res.status < 500 and res.status != 408 and res.status != 429) {
    return f'Salesforce rejected the request (status {res.status}, {detail}). Retrying will not help. Check the object permissions, the field values, and the object path in Salesforce.'
  }
  return f'Salesforce request failed with status {res.status}: {res.body}'
}

if (res.status >= 400) {
  throw Error(salesforceError(res));
} else {
  print(res.status, res.body)
}
""".strip()

common_inputs = {
    "oauth": {
        "key": "oauth",
        "type": "integration",
        "integration": "salesforce",
        "label": "Salesforce account",
        "requiredScopes": "refresh_token full",
        "secret": False,
        "required": True,
    }
}

template_create: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-salesforce-create",
    name="Salesforce",
    description="Create objects in Salesforce",
    icon_url="/static/services/salesforce.png",
    category=["CRM", "Customer Success"],
    code_language="hog",
    code="""
let getPayload := () -> {
  let properties := {}
  if (inputs.include_all_event_properties) {
    if (not empty(event.elements_chain)) {
      properties['$elements_chain'] := event.elements_chain
    }
    for (let key, value in event.properties) {
      properties[key] := value
    }
  }
  if (inputs.include_all_person_properties) {
    for (let key, value in person.properties) {
      properties[key] := value
    }
  }
  for (let key, value in inputs.properties) {
    properties[key] := value
  }
  return properties
}

let res := fetch(f'{inputs.oauth.instance_url}/services/data/v61.0/sobjects/{inputs.path}', {
  'body': getPayload(),
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.oauth.access_token}',
    'Content-Type': 'application/json'
  }
});
""".strip()
    + "\n\n"
    + error_handling_hog,
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
            "key": "include_all_event_properties",
            "type": "boolean",
            "label": "Include all event properties as attributes",
            "description": "If set, all event properties will be included as attributes. Individual attributes can be overridden below.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "include_all_person_properties",
            "type": "boolean",
            "label": "Include all person properties as attributes",
            "description": "If set, all person properties will be included as attributes. Individual attributes can be overridden below.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "json",
            "label": "Additional properties",
            "description": "Additional properties for the Salesforce Object.",
            "default": {
                "email": "{person.properties.email}",
            },
            "secret": False,
            "required": True,
        },
    ],
    filters=common_filters,
)

template_update: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-salesforce-update",
    name="Salesforce",
    description="Update or create objects in Salesforce. Salesforce upserts on the object path: it updates the record that matches, or creates a new record when none matches.",
    icon_url="/static/services/salesforce.png",
    category=["CRM", "Customer Success"],
    code_language="hog",
    code="""
let getPayload := () -> {
  let properties := {}
  if (inputs.include_all_event_properties) {
    for (let key, value in event.properties) {
      properties[key] := value
    }
  }
  if (inputs.include_all_person_properties) {
    for (let key, value in person.properties) {
      properties[key] := value
    }
  }
  for (let key, value in inputs.properties) {
    properties[key] := value
  }
  return properties
}

let res := fetch(f'{inputs.oauth.instance_url}/services/data/v61.0/sobjects/{inputs.path}', {
  'body': getPayload(),
  'method': 'PATCH',
  'headers': {
    'Authorization': f'Bearer {inputs.oauth.access_token}',
    'Content-Type': 'application/json'
  }
});
""".strip()
    + "\n\n"
    + error_handling_hog,
    inputs_schema=[
        common_inputs["oauth"],
        {
            "key": "path",
            "type": "string",
            "label": "Object path (upsert)",
            "description": "The path to the record to upsert, in the form Object/ExternalIdField/value. For example, Lead/Email/{person.properties.email} matches a lead by email. Salesforce updates the matching record, or creates a new record when none matches. A bare object name like 'Contact' points at the collection and fails with METHOD_NOT_ALLOWED, so it does not work here. The external ID value must not be empty. See https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/dome_upsert.htm for more information.",
            "default": "Lead/Email/{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "include_all_event_properties",
            "type": "boolean",
            "label": "Include all event properties as attributes",
            "description": "If set, all event properties will be included as attributes. Individual attributes can be overridden below.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "include_all_person_properties",
            "type": "boolean",
            "label": "Include all person properties as attributes",
            "description": "If set, all person properties will be included as attributes. Individual attributes can be overridden below.",
            "default": False,
            "secret": False,
            "required": True,
        },
        {
            "key": "properties",
            "type": "json",
            "label": "Additional properties",
            "description": "Additional properties for the Salesforce Object.",
            "default": {
                "email": "{person.properties.email}",
                "browser": "{event.properties.$browser}",
            },
            "secret": False,
            "required": True,
        },
    ],
    filters=common_filters,
)


class TemplatSalesforceMigrator(HogFunctionTemplateMigrator):
    plugin_url = "https://github.com/PostHog/posthog-plugin-replicator"

    @classmethod
    def migrate(cls, obj):
        eventPath = obj.config.get("eventPath", "")
        eventsToInclude = [x.strip() for x in obj.config.get("eventsToInclude", "").split(",") if x]
        eventMethodType = obj.config.get("eventMethodType", "")
        propertiesToInclude = [x.strip() for x in obj.config.get("propertiesToInclude", "").split(",") if x]

        # This will be everybody currently on cloud
        if eventMethodType == "POST":
            hf = deepcopy(dataclasses.asdict(template_create))
        else:
            hf = deepcopy(dataclasses.asdict(template_update))

        hf["inputs"] = {
            "path": {"value": eventPath},
        }

        hf["filters"] = {}
        if eventsToInclude:
            hf["filters"]["events"] = [
                {
                    "id": event,
                    "name": event,
                    "type": "events",
                    "order": 0,
                }
                for event in eventsToInclude
            ]

        if propertiesToInclude:
            hf["inputs"]["properties"] = {
                "value": {prop: f"{{event.properties.{prop}}}" for prop in propertiesToInclude}
            }
        elif eventsToInclude and "$identify" in eventsToInclude:
            hf["inputs"]["include_all_person_properties"] = {"value": True}
        else:
            hf["inputs"]["include_all_event_properties"] = {"value": True}

        return hf
