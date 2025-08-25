from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# See https://dashboard.clearbit.com/docs#enrichment-api-combined-api

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-clearbit",
    name="Clearbit",
    description="Loads data from the Clearbit API and tracks an additional event with the enriched data if found. Once enriched, the person will not be enriched again.",
    icon_url="/static/services/clearbit.png",
    category=["Analytics"],
    code_language="hog",
    code="""
let api_key := inputs.api_key
let email := inputs.email

if (empty(email) or event.event == '$set' or person.properties.clearbit_enriched) {
    return false
}

let response := fetch(f'https://person-stream.clearbit.com/v2/combined/find?email={email}', {
    'method': 'GET',
    'headers': {
        'Authorization': f'Bearer {api_key}'
    }
})
if (response.status == 200 and not empty(response.body.person)) {
    print('Clearbit data found - sending event to PostHog')
    postHogCapture({
        'event': '$set',
        'distinct_id': event.distinct_id,
        'properties': {
            '$lib': 'hog_function',
            '$hog_function_source': source.url,
            '$set_once': {
                'person': response.body.person,
                'company': response.body.company,
                'clearbit_enriched': true
            }
        }
    })
} else {
    print('No Clearbit data found')
}
""".strip(),
    inputs_schema=[
        {
            "key": "api_key",
            "type": "string",
            "label": "Clearbit API Key",
            "secret": True,
            "required": True,
        },
        {
            "key": "email",
            "type": "string",
            "label": "Email of the user",
            "description": "Where to find the email for the user to be checked with Clearbit",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
    ],
)
