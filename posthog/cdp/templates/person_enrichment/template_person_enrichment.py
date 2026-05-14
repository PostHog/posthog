from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# Real-time person enrichment via People Data Labs (PDL).
#
# Listens for `$identify` events (or any event tied to a person whose email is
# known), looks the person up in PDL by email, and writes the curated set of
# `$enriched_*` properties back via a `$set` event. Mirrors the curated field
# shape used by the bulk Temporal workflow at
# `posthog/temporal/people_enrichment/workflow.py` so consumers see one schema
# regardless of which path enriched the person.
#
# Dedupe: skips when `person.properties.$enriched_at` is already set — set
# alongside the rest of the `$enriched_*` fields, so a single successful run
# prevents repeat lookups on every subsequent event from the same person.
#
# PDL sentinel booleans: plan-gated fields surface as the literal value `true`
# or `false` rather than strings. We filter those out with `typeof(...) ==
# 'string'` guards so they never reach person properties.

template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    status="beta",
    free=False,
    type="destination",
    id="template-person-enrichment-pdl",
    name="Person enrichment (PDL)",
    description=(
        "Enriches identified persons in real time using the People Data Labs API. "
        "Writes `$enriched_full_name`, `$enriched_job_title`, `$enriched_linkedin_url`, "
        "`$enriched_location`, `$enriched_professional_email`, `$enriched_personal_email`, "
        "and `$enriched_at` to the person via a `$set` event. Skips persons already "
        "enriched (gated by `$enriched_at`)."
    ),
    icon_url="/static/services/posthog.png",
    category=["Customer Success"],
    code_language="hog",
    filters={
        "events": [{"id": "$identify", "name": "$identify", "type": "events", "order": 0}],
    },
    code="""
// Avoid emitting on our own writes to prevent infinite loops.
if (event.event == '$set' or event.event == '$groupidentify') {
    return false
}

// Dedupe: a person is enriched at most once. The orchestration layer can clear
// `$enriched_at` if a re-enrichment is desired.
if (not empty(person.properties.$enriched_at)) {
    return false
}

let email := inputs.email
if (empty(email)) {
    print('No email available, skipping enrichment')
    return false
}

let pdl_api_key := inputs.pdl_api_key
if (empty(pdl_api_key)) {
    print('PDL API key not configured, skipping enrichment')
    return false
}

// Pass the API key as a header rather than a query parameter. Query strings
// appear verbatim in server-side access logs on both sides of the connection,
// so embedding the credential there is a needless exposure surface. The email
// has to stay in the URL — PDL's `/person/enrich` requires it there.
//
// Encode the email — values like `a@example.com&profile=...` could otherwise
// inject extra PDL query parameters into a request made with our API key.
let pdl_url := f'https://api.peopledatalabs.com/v5/person/enrich?email={encodeURLComponent(email)}&min_likelihood=4'
let response := fetch(pdl_url, {'method': 'GET', 'headers': {'X-Api-Key': pdl_api_key}})

// 404 means PDL has no record matching this email. Stamp `$enriched_at` so
// the gate at the top of the template blocks retries for this person —
// otherwise a replayed `$identify` for the same address would re-burn quota
// on every attempt. We only stamp on confirmed no-match; 402 (credits
// exhausted) and other failure modes are transient, so we leave the gate
// open for a later retry.
if (response.status == 404) {
    print('PDL no match for', email)
    postHogCapture({
        'event': '$set',
        'distinct_id': event.distinct_id,
        'properties': {
            '$lib': 'hog_function',
            '$hog_function_source': source.url,
            '$set': {'$enriched_at': now()}
        }
    })
    return false
}
if (response.status == 402) {
    print('PDL out of credits, exiting')
    return false
}
if (response.status != 200 or empty(response.body.data)) {
    print('PDL unexpected response', response.status)
    return false
}

let data := response.body.data

// Curated field extraction. PDL returns sentinel booleans (`true` / `false`)
// for fields gated behind plan tier — `typeof(...) == 'string'` discards those.
fn pickString(value) {
    if (typeof(value) == 'string' and not empty(value)) {
        return value
    }
    return null
}

let full_name := pickString(data.full_name)
let job_title := pickString(data.job_title)
let linkedin_url := pickString(data.linkedin_url)
let professional_email := pickString(data.work_email)

// Location: PDL gates the granular fields (name / locality / region) behind
// upgraded plans, but `location_country` and `location_continent` remain
// accessible — walk the chain so we resolve to whatever's actually populated.
let location := pickString(data.location_name)
if (empty(location)) { location := pickString(data.location_locality) }
if (empty(location)) { location := pickString(data.location_region) }
if (empty(location)) { location := pickString(data.location_country) }
if (empty(location)) { location := pickString(data.location_continent) }

let personal_email := null
if (typeof(data.personal_emails) == 'array') {
    for (let candidate in data.personal_emails) {
        if (empty(personal_email)) {
            personal_email := pickString(candidate)
        }
    }
}

let set_props := {'$enriched_at': now()}
if (not empty(full_name)) { set_props.$enriched_full_name := full_name }
if (not empty(job_title)) { set_props.$enriched_job_title := job_title }
if (not empty(linkedin_url)) { set_props.$enriched_linkedin_url := linkedin_url }
if (not empty(location)) { set_props.$enriched_location := location }
if (not empty(professional_email)) { set_props.$enriched_professional_email := professional_email }
if (not empty(personal_email)) { set_props.$enriched_personal_email := personal_email }

print('Enriched person', email)
postHogCapture({
    'event': '$set',
    'distinct_id': event.distinct_id,
    'properties': {
        '$lib': 'hog_function',
        '$hog_function_source': source.url,
        '$set': set_props
    }
})
""".strip(),
    inputs_schema=[
        {
            "key": "pdl_api_key",
            "type": "string",
            "label": "People Data Labs API key",
            "secret": True,
            "required": True,
        },
        {
            "key": "email",
            "type": "string",
            "label": "Email to enrich",
            "description": "Where to read the email for the person being enriched. Defaults to the person's `email` property.",
            "default": "{person.properties.email}",
            "secret": False,
            "required": True,
        },
    ],
)
