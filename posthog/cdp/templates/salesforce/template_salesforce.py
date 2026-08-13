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

let path := trim(inputs.path)

// Values templated into the path resolve to an empty string when the property is unset, which
// silently produces a URL Salesforce rejects. Fail here so the message names the real cause.
for (let segment in splitByString('/', path)) {
  if (empty(trim(segment))) {
    throw Error(f'Salesforce object path \\'{path}\\' is missing a value. A property mapped into the path was empty when this ran. Check that it is set before this step.')
  }
}

let res := fetch(f'{inputs.oauth.instance_url}/services/data/v61.0/sobjects/{path}', {
  'body': getPayload(),
  'method': 'POST',
  'headers': {
    'Authorization': f'Bearer {inputs.oauth.access_token}',
    'Content-Type': 'application/json'
  }
});

if (res.status >= 400) {
  throw Error(f'Salesforce request to \\'{path}\\' failed with status {res.status}: {res.body}');
}

print(res.status, res.body)
return res.body
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

let path := trim(inputs.path)
let segments := splitByString('/', path)

// Values templated into the path resolve to an empty string when the property is unset. That
// truncates the URL to the object collection, which only accepts GET, HEAD, and POST, so
// Salesforce answers the PATCH with a 405 that says nothing about the missing value.
for (let segment in segments) {
  if (empty(trim(segment))) {
    throw Error(f'Salesforce object path \\'{path}\\' is missing a value. A property mapped into the path was empty when this ran. Check that it is set before this step.')
  }
}

if (length(segments) < 2) {
  throw Error(f'Salesforce object path \\'{path}\\' has no record identifier. Use \\'Object/RecordId\\' to update by record ID, or \\'Object/ExternalIdField/Value\\' to update by external ID.')
}

let res := fetch(f'{inputs.oauth.instance_url}/services/data/v61.0/sobjects/{path}', {
  'body': getPayload(),
  'method': 'PATCH',
  'headers': {
    'Authorization': f'Bearer {inputs.oauth.access_token}',
    'Content-Type': 'application/json'
  }
});

if (res.status >= 400) {
  throw Error(f'Salesforce request to \\'{path}\\' failed with status {res.status}: {res.body}');
}

print(res.status, res.body)

// Updating a record by ID answers with no body, so hand back a shape a workflow can read
// either way. An upsert already returns success alongside the id it touched.
return empty(res.body) ? {'success': true} : res.body
""".strip(),
    inputs_schema=[
        common_inputs["oauth"],
        {
            "key": "path",
            "type": "string",
            "label": "Object path",
            "description": "The object and record to update. Use `Lead/{recordId}` to update by record ID, or `Lead/Email/{person.properties.email}` to update by an external ID field, which must be flagged as an External ID in Salesforce. A bare object name like `Lead` is not valid for updates. Updating by external ID creates the record when nothing matches. See https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/dome_upsert.htm for more information.",
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


template_lookup: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-salesforce-lookup",
    name="Salesforce",
    description="Look up an object in Salesforce",
    icon_url="/static/services/salesforce.png",
    category=["CRM", "Customer Success"],
    code_language="hog",
    code=r"""
let assertApiName := (value, label, pattern) -> {
  if (not match(value, pattern)) {
    throw Error(f'{label} \'{value}\' is not a valid Salesforce API name. Use letters, numbers, and underscores.')
  }
}

// Backslash goes first, otherwise the sequences introduced below get escaped a second time.
let escapeSoql := (value) -> {
  let escaped := replaceAll(value, '\\', '\\\\')
  escaped := replaceAll(escaped, '\'', '\\\'')
  escaped := replaceAll(escaped, '\n', '\\n')
  escaped := replaceAll(escaped, '\r', '\\r')
  escaped := replaceAll(escaped, '\t', '\\t')
  escaped := replaceAll(escaped, '\b', '\\b')
  escaped := replaceAll(escaped, '\f', '\\f')
  return escaped
}

// The query travels in the URL, so percent-encode anything that would end the query
// string or change its meaning. Percent signs go first, otherwise the replacements
// below get encoded a second time.
let encodeForUrl := (value) -> {
  let encoded := replaceAll(value, '%', '%25')
  encoded := replaceAll(encoded, ' ', '%20')
  encoded := replaceAll(encoded, '"', '%22')
  encoded := replaceAll(encoded, '#', '%23')
  encoded := replaceAll(encoded, '&', '%26')
  encoded := replaceAll(encoded, '\'', '%27')
  encoded := replaceAll(encoded, '+', '%2B')
  encoded := replaceAll(encoded, ',', '%2C')
  encoded := replaceAll(encoded, '/', '%2F')
  encoded := replaceAll(encoded, '<', '%3C')
  encoded := replaceAll(encoded, '=', '%3D')
  encoded := replaceAll(encoded, '>', '%3E')
  encoded := replaceAll(encoded, '?', '%3F')
  encoded := replaceAll(encoded, '\\', '%5C')
  return encoded
}

let object := trim(inputs.object)
let matchField := trim(inputs.match_field)
let matchValue := trim(inputs.match_value)

if (empty(matchValue)) {
  throw Error('Salesforce lookup has no value to match on. The property mapped to the match value was empty when this ran. Check that it is set before this step.')
}

assertApiName(object, 'Object', '^[A-Za-z0-9_]+$')
assertApiName(matchField, 'Match field', '^[A-Za-z0-9_]+$')

let selected := ['Id']
for (let rawField in splitByString(',', inputs.fields ?? '')) {
  let field := trim(rawField)
  if (notEmpty(field) and not has(selected, field)) {
    assertApiName(field, 'Field', '^[A-Za-z0-9_.]+$')
    selected := arrayPushBack(selected, field)
  }
}

let selectList := arrayStringConcat(selected, ', ')
let escapedValue := escapeSoql(matchValue)

// Two rows are enough to tell a unique match from an ambiguous one. This bounds the
// row count only. One long field still exceeds the workflow variable limit, which is
// why the returned fields are listed explicitly rather than selected wholesale.
let soql := f'SELECT {selectList} FROM {object} WHERE {matchField} = \'{escapedValue}\' LIMIT 2'
let queryString := encodeForUrl(soql)

let res := fetch(f'{inputs.oauth.instance_url}/services/data/v61.0/query/?q={queryString}', {
  'method': 'GET',
  'headers': {
    'Authorization': f'Bearer {inputs.oauth.access_token}',
    'Content-Type': 'application/json'
  }
});

if (res.status >= 400) {
  throw Error(f'Salesforce lookup on {object} failed with status {res.status}: {res.body}');
}

let records := res.body?.records ?? []
let found := length(records) > 0

print(f'Salesforce lookup on {object} matched {length(records)} record(s)')

return {
  'found': found,
  'multiple': length(records) > 1,
  'id': found ? records[1].Id : null,
  'record': found ? records[1] : null
}
""".strip(),
    inputs_schema=[
        common_inputs["oauth"],
        {
            "key": "object",
            "type": "string",
            "label": "Object",
            "description": "The Salesforce object to search, such as `Lead` or `Contact`.",
            "default": "Lead",
            "secret": False,
            "required": True,
        },
        {
            "key": "match_field",
            "type": "string",
            "label": "Match field",
            "description": "The field to match on, such as `Email`. Unlike the update step, this does not have to be an External ID field.",
            "default": "Email",
            "secret": False,
            "required": True,
        },
        {
            "key": "match_value",
            "type": "string",
            "label": "Match value",
            "description": "The value to match. The step fails if this is empty, so map it to a property that is set by the time the step runs.",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
        {
            "key": "fields",
            "type": "string",
            "label": "Fields to return",
            "description": "Comma separated fields to return on the matched record. `Id` is always included. Workflow variables share a 5 KB limit, so avoid long text fields here, or set a result path on the output variable to store only what you need.",
            "default": "Id",
            "secret": False,
            "required": False,
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
