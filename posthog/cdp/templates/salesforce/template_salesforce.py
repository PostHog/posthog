import dataclasses
from copy import deepcopy

from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC, HogFunctionTemplateMigrator

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

if (res.status >= 400) {
  throw Error(f'Salesforce request failed with status {res.status}: {res.body}');
} else {
  print(res.status, res.body)
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
    description="Update objects in Salesforce",
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

if (res.status >= 400) {
  throw Error(f'Salesforce request failed with status {res.status}: {res.body}');
} else {
  print(res.status, res.body)
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
