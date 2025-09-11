from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-airtable",
    name="Airtable",
    description="Creates Airtable records",
    icon_url="/static/services/airtable.png",
    category=["Custom"],
    code_language="hog",
    code="""
let url := f'https://api.airtable.com/v0/{inputs.base_id}/{inputs.table_name}'

let payload := {
  'headers': {
    'Content-Type': 'application/json',
    'Authorization': f'Bearer {inputs.access_token}'
  },
  'body': {
    'fields': inputs.fields,
    'typecast': true
  },
  'method': 'POST'
}

if (inputs.debug) {
  print('Request', url, payload)
}

let res := fetch(url, payload);

if (inputs.debug) {
  print('Response', res.status, res.body);
}
if (res.status >= 400) {
    throw Error(f'Error from api.airtable.com (status {res.status}): {res.body}')
}
""".strip(),
    inputs_schema=[
        {
            "key": "access_token",
            "type": "string",
            "label": "Airtable access token",
            "secret": True,
            "required": True,
            "description": "Create this at https://airtable.com/create/tokens",
        },
        {
            "key": "base_id",
            "type": "string",
            "label": "Airtable base ID",
            "secret": False,
            "required": True,
            "description": "Find this at https://airtable.com/developers/web/api/introduction",
        },
        {
            "key": "table_name",
            "type": "string",
            "label": "Table name",
            "secret": False,
            "required": True,
        },
        {
            "key": "fields",
            "type": "json",
            "label": "Fields",
            "default": {"Timestamp": "{event.timestamp}", "Person Name": "{person.name}"},
            "secret": False,
            "required": True,
            "description": "Map field names from Airtable to properties from events and person records.",
        },
        {
            "key": "debug",
            "type": "boolean",
            "label": "Log responses",
            "description": "Logs the response of http calls for debugging.",
            "secret": False,
            "required": False,
            "default": False,
        },
    ],
)
