from posthog.cdp.templates.hog_function_template import HogFunctionTemplate


# See https://dashboard.clearbit.com/docs#enrichment-api-combined-api

template: HogFunctionTemplate = HogFunctionTemplate(
    status="alpha",
    id="template-clearbit",
    name="Enrich with Clearbit",
    description="Enriches the incoming event data with Clearbit data",
    icon_url="/api/projects/@current/hog_functions/icon/?id=clearbit.com",
    hog="""
let api_key := inputs.api_key
let email := inputs.email
if (empty(email)) {
    return false
}
if (person.properties.clearbit_enriched) {
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
        'event': 'clearbit_enriched',
        'distinct_id': event.distinct_id,
        'properties': {
            '$set_once': {
                'person': response.body.person,
                'company': response.body.company
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
