from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

# Real-time organization (group) enrichment via Harmonic.
#
# Listens for `$groupidentify` events tied to the `organization` group type and,
# when the group exposes a usable domain, calls Harmonic's
# `enrichCompanyByIdentifiers` mutation. The curated `$enriched_org_*` set is
# written back via a follow-up `$groupidentify` event with `$group_set` — same
# shape and key namespace produced by the bulk Temporal workflow at
# `posthog/temporal/organization_enrichment/workflow.py`.
#
# Dedupe: relies on the incoming event's `$group_set` not already containing
# `$enriched_org_name`. This is a coarse guard against immediate loops (our own
# follow-up event); a stronger TTL-style dedupe needs the group's stored
# properties, which aren't reliably exposed to hog functions yet.

HARMONIC_QUERY = """mutation($identifiers: CompanyEnrichmentIdentifiersInput!) {
  enrichCompanyByIdentifiers(identifiers: $identifiers) {
    companyFound
    company {
      name
      website { domain url }
      headcount
      description
      location { city country state }
      foundingDate { date }
      funding {
        fundingTotal
        numFundingRounds
        lastFundingAt
        lastFundingType
        lastFundingTotal
        fundingStage
      }
      tractionMetrics {
        webTraffic { latestMetricValue }
        linkedinFollowerCount { latestMetricValue }
        twitterFollowerCount { latestMetricValue }
      }
    }
  }
}"""


template: HogFunctionTemplateDC = HogFunctionTemplateDC(
    # `hidden` keeps this out of the public template gallery; combined with the
    # runtime `project.id` guard below, only team 2 ("🎉 PostHog App + Website")
    # can use it. Flip to `beta` if rolling out to additional teams.
    status="hidden",
    free=False,
    type="destination",
    id="template-organization-enrichment-harmonic",
    name="Organization enrichment (Harmonic)",
    description=(
        "Enriches organization groups in real time using the Harmonic API. "
        "Writes `$enriched_org_name`, `$enriched_org_domain`, `$enriched_org_headcount`, "
        "`$enriched_org_headquarters`, `$enriched_org_funding_stage`, "
        "`$enriched_org_funding_total`, and related fields to the group via a "
        "`$groupidentify` event."
    ),
    icon_url="/static/services/posthog.png",
    category=["Customer Success"],
    code_language="hog",
    filters={
        "events": [{"id": "$groupidentify", "name": "$groupidentify", "type": "events", "order": 0}],
    },
    code=(
        """
// Scoped to team 2 (`🎉 PostHog App + Website`) — matches the `hidden` status.
// Other teams won't reach this hog function via the template gallery, but if
// they're given access to the template via API this guard still refuses to run.
if (project.id != 2) {
    return false
}

// We only enrich the `organization` group type. Other group types pass through.
if (event.properties.$group_type != inputs.group_type) {
    return false
}

let group_key := event.properties.$group_key
if (empty(group_key)) {
    return false
}

// Coarse loop guard: if our own follow-up $groupidentify already carries the
// enriched name, skip. A stronger TTL-style dedupe needs durable group state.
if (not empty(event.properties.$group_set.$enriched_org_name)) {
    return false
}

let domain := inputs.domain
if (empty(domain)) {
    print('No domain available for group', group_key)
    return false
}

let api_key := inputs.harmonic_api_key
if (empty(api_key)) {
    print('Harmonic API key not configured, skipping enrichment')
    return false
}

// Normalize the domain — Harmonic expects a clean host (no protocol, no www).
let clean_domain := replaceAll(replaceAll(replaceAll(lower(trim(domain)), 'https://', ''), 'http://', ''), 'www.', '')

let body := {
    'query': inputs.query,
    'variables': {'identifiers': {'websiteUrl': f'https://{clean_domain}'}}
}

let response := fetch(f'https://api.harmonic.ai/graphql?apikey={api_key}', {
    'method': 'POST',
    'headers': {'Content-Type': 'application/json'},
    'body': body
})

if (response.status != 200) {
    print('Harmonic unexpected status', response.status)
    return false
}
if (not empty(response.body.errors)) {
    print('Harmonic returned errors')
    return false
}

let result := response.body.data.enrichCompanyByIdentifiers
if (empty(result) or not result.companyFound or empty(result.company)) {
    print('Harmonic no match for', clean_domain)
    return false
}

let company := result.company

fn pickString(value) {
    if (typeof(value) == 'string' and not empty(value)) {
        return value
    }
    return null
}

fn pickNumber(value) {
    if (typeof(value) == 'integer' or typeof(value) == 'float') {
        return value
    }
    return null
}

let website := company.website
if (empty(website)) { website := {} }
let location := company.location
if (empty(location)) { location := {} }
let founding := company.foundingDate
if (empty(founding)) { founding := {} }
let funding := company.funding
if (empty(funding)) { funding := {} }
let traction := company.tractionMetrics
if (empty(traction)) { traction := {} }
let web_traffic := traction.webTraffic
if (empty(web_traffic)) { web_traffic := {} }
let linkedin_followers := traction.linkedinFollowerCount
if (empty(linkedin_followers)) { linkedin_followers := {} }
let twitter_followers := traction.twitterFollowerCount
if (empty(twitter_followers)) { twitter_followers := {} }

let city := pickString(location.city)
let state := pickString(location.state)
let country := pickString(location.country)
let headquarters_parts := []
if (not empty(city)) { headquarters_parts := arrayPushBack(headquarters_parts, city) }
if (not empty(state)) { headquarters_parts := arrayPushBack(headquarters_parts, state) }
if (not empty(country)) { headquarters_parts := arrayPushBack(headquarters_parts, country) }
let headquarters := null
if (not empty(headquarters_parts)) {
    headquarters := arrayStringConcat(headquarters_parts, ', ')
}

let founded_year := null
let founded_date := pickString(founding.date)
if (not empty(founded_date) and length(founded_date) >= 4) {
    founded_year := toInt(substring(founded_date, 1, 4))
}

let group_set := {'$enriched_at': now()}
let name := pickString(company.name)
if (not empty(name)) { group_set.$enriched_org_name := name }
let domain_clean := pickString(website.domain)
if (not empty(domain_clean)) { group_set.$enriched_org_domain := domain_clean }
let description := pickString(company.description)
if (not empty(description)) { group_set.$enriched_org_description := description }
let headcount := pickNumber(company.headcount)
if (not empty(headcount)) { group_set.$enriched_org_headcount := headcount }
if (not empty(headquarters)) { group_set.$enriched_org_headquarters := headquarters }
if (not empty(city)) { group_set.$enriched_org_city := city }
if (not empty(state)) { group_set.$enriched_org_state := state }
if (not empty(country)) { group_set.$enriched_org_country := country }
if (not empty(founded_year)) { group_set.$enriched_org_founded_year := founded_year }
let funding_stage := pickString(funding.fundingStage)
if (not empty(funding_stage)) { group_set.$enriched_org_funding_stage := funding_stage }
let last_funding_type := pickString(funding.lastFundingType)
if (not empty(last_funding_type)) { group_set.$enriched_org_last_funding_type := last_funding_type }
let last_funding_amount := pickNumber(funding.lastFundingTotal)
if (not empty(last_funding_amount)) { group_set.$enriched_org_last_funding_amount := last_funding_amount }
let last_funding_at := pickString(funding.lastFundingAt)
if (not empty(last_funding_at)) { group_set.$enriched_org_last_funding_at := last_funding_at }
let funding_total := pickNumber(funding.fundingTotal)
if (not empty(funding_total)) { group_set.$enriched_org_funding_total := funding_total }
let funding_rounds := pickNumber(funding.numFundingRounds)
if (not empty(funding_rounds)) { group_set.$enriched_org_num_funding_rounds := funding_rounds }
let web_traffic_value := pickNumber(web_traffic.latestMetricValue)
if (not empty(web_traffic_value)) { group_set.$enriched_org_web_traffic_latest := web_traffic_value }
let linkedin_followers_value := pickNumber(linkedin_followers.latestMetricValue)
if (not empty(linkedin_followers_value)) { group_set.$enriched_org_linkedin_followers := linkedin_followers_value }
let twitter_followers_value := pickNumber(twitter_followers.latestMetricValue)
if (not empty(twitter_followers_value)) { group_set.$enriched_org_twitter_followers := twitter_followers_value }

print('Enriched organization', group_key, clean_domain)
postHogCapture({
    'event': '$groupidentify',
    'distinct_id': event.distinct_id,
    'properties': {
        '$lib': 'hog_function',
        '$hog_function_source': source.url,
        '$group_type': inputs.group_type,
        '$group_key': group_key,
        '$group_set': group_set
    }
})
"""
    ).strip(),
    inputs_schema=[
        {
            "key": "harmonic_api_key",
            "type": "string",
            "label": "Harmonic API key",
            "secret": True,
            "required": True,
        },
        {
            "key": "group_type",
            "type": "string",
            "label": "Group type to enrich",
            "description": "Only `$groupidentify` events for this group type trigger enrichment.",
            "default": "organization",
            "secret": False,
            "required": True,
        },
        {
            "key": "domain",
            "type": "string",
            "label": "Domain to enrich",
            "description": (
                "Where to read the company domain from the incoming event. Defaults to "
                "`$group_set.domain` — adjust if your client SDK stores the domain under "
                "a different property name."
            ),
            "default": "{event.properties.$group_set.domain}",
            "secret": False,
            "required": True,
        },
        {
            "key": "query",
            "type": "string",
            "label": "Harmonic GraphQL query",
            "description": (
                "The enrichment mutation sent to Harmonic. The default returns the curated "
                "field set this template knows how to extract; modify with care."
            ),
            "default": HARMONIC_QUERY,
            "secret": False,
            "required": True,
        },
    ],
)
