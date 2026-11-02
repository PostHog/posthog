import { mswDecorator } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

const EVENT_PROPERTIES = [
    { id: '1', name: '$browser', property_type: 'String', is_numerical: false },
    { id: '2', name: '$current_url', property_type: 'String', is_numerical: false },
    { id: '3', name: '$os', property_type: 'String', is_numerical: false },
    { id: '4', name: '$browser_version', property_type: 'Numeric', is_numerical: true },
    { id: '5', name: 'plan', property_type: 'String', is_numerical: false },
    { id: '11', name: '$geoip_country_code', property_type: 'String', is_numerical: false },
    { id: '12', name: 'utm_source', property_type: 'String', is_numerical: false },
]

const PERSON_PROPERTIES = [
    { id: '6', name: 'email', property_type: 'String', is_numerical: false },
    { id: '7', name: 'signed_up_at', property_type: 'DateTime', is_numerical: false },
]

const FEATURE_FLAG_PROPERTIES = [
    { id: '8', name: '$feature/new-checkout', property_type: 'String', is_numerical: false },
]

const SESSION_PROPERTIES = [
    { id: '9', name: '$entry_pathname', property_type: 'String', is_numerical: false },
    { id: '10', name: '$session_duration', property_type: 'Duration', is_numerical: true },
]

const EVENT_DEFINITIONS = [
    { id: '1', name: '$pageview' },
    { id: '2', name: '$autocapture' },
    { id: '3', name: '$exception' },
    { id: '4', name: 'signed_up' },
]

const EVENT_VALUES: Record<string, string[]> = {
    $browser: ['Chrome', 'Firefox', 'Safari', 'Edge'],
    $os: ['iOS', 'Android', 'Mac OS X', 'Windows'],
    $geoip_country_code: ['FR', 'DE', 'US', 'GB'],
    $current_url: ['https://example.com/pricing', 'https://example.com/docs'],
    $browser_version: ['118', '120', '121', '130'],
}

/** Property definitions, event definitions, cohorts and values that the filter bar stories load. */
export const filterBarStoryDecorator = mswDecorator({
    get: {
        '/api/projects/:team_id/property_definitions/': ({ request }) => {
            const url = new URL(request.url)
            const search = (url.searchParams.get('search') ?? '').toLowerCase()
            const type = url.searchParams.get('type')
            const flags = url.searchParams.get('is_feature_flag')
            const source =
                type === 'person' ? PERSON_PROPERTIES : flags === 'true' ? FEATURE_FLAG_PROPERTIES : EVENT_PROPERTIES
            return toPaginatedResponse(source.filter((property) => property.name.includes(search)))
        },
        '/api/projects/:team_id/event_definitions/': ({ request }) => {
            const search = (new URL(request.url).searchParams.get('search') ?? '').toLowerCase()
            return toPaginatedResponse(EVENT_DEFINITIONS.filter((event) => event.name.includes(search)))
        },
        '/api/projects/:team_id/sessions/property_definitions/': ({ request }) => {
            const search = (new URL(request.url).searchParams.get('search') ?? '').toLowerCase()
            return toPaginatedResponse(SESSION_PROPERTIES.filter((property) => property.name.includes(search)))
        },
        '/api/projects/:team_id/cohorts/': toPaginatedResponse([
            { id: 1, name: 'Power users', count: 120 },
            { id: 2, name: 'Trial accounts', count: 48 },
        ]),
        '/api/event/values/': ({ request }) => {
            const key = new URL(request.url).searchParams.get('key') ?? ''
            return { results: (EVENT_VALUES[key] ?? EVENT_VALUES.$browser).map((name) => ({ name })) }
        },
        '/api/person/values/': { results: [{ name: 'alice@example.com' }, { name: 'bob@example.com' }] },
    },
})
