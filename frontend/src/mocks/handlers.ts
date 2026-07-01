import {
    MOCK_DATA_COLOR_THEMES,
    MOCK_DEFAULT_COHORT,
    MOCK_DEFAULT_ORGANIZATION,
    MOCK_DEFAULT_ORGANIZATION_INVITE,
    MOCK_DEFAULT_ORGANIZATION_MEMBER,
    MOCK_DEFAULT_PLUGIN,
    MOCK_DEFAULT_PLUGIN_CONFIG,
    MOCK_DEFAULT_TEAM,
    MOCK_DEFAULT_USER,
    MOCK_PERSON_PROPERTIES,
    MOCK_SECOND_ORGANIZATION_MEMBER,
    MOCK_EXPERIMENTS_STATS_RESPONSE,
} from 'lib/api.mock'

import { HttpResponse } from 'msw'

import { STATUS_PAGE_BASE } from 'lib/components/HelpMenu/incidentStatusLogic'

import sdkVersions from '~/mocks/fixtures/api/sdk_versions.json'
import teamSdkVersions from '~/mocks/fixtures/api/team_sdk_versions.json'
import { SharingConfigurationType } from '~/types'

import { getAvailableProductFeatures } from './features'
import { billingJson } from './fixtures/_billing'
import _hogFunctionTemplatesDestinations from './fixtures/_hogFunctionTemplatesDestinations.json'
import _hogFunctionTemplatesTransformations from './fixtures/_hogFunctionTemplatesTransformations.json'
import _instanceStatus from './fixtures/_instance_status.json'
import _preflight from './fixtures/_preflight.json'
import * as statusPageAllOK from './fixtures/_status_page_all_ok.json'
import _systemStatus from './fixtures/_system_status.json'
import { MockResolverInfo, MockSignature, Mocks, mocksToHandlers } from './utils'

export const EMPTY_PAGINATED_RESPONSE = {
    count: 0,
    results: [] as any[],
    next: null,
    previous: null,
}
export const toPaginatedResponse = (results: any[]): typeof EMPTY_PAGINATED_RESPONSE => ({
    count: results.length,
    results,
    next: null,
    previous: null,
})

const hogFunctionTemplateRetrieveMock: MockSignature = ({ params }) => {
    const hogFunctionTemplate =
        _hogFunctionTemplatesDestinations.results.find((conf) => conf.id === params.id) ||
        _hogFunctionTemplatesTransformations.results.find((conf) => conf.id === params.id)
    if (!hogFunctionTemplate) {
        return new HttpResponse(null, { status: 404 })
    }
    return HttpResponse.json({ ...hogFunctionTemplate })
}

const hogFunctionTemplatesMock: MockSignature = ({ request }) => {
    const types = new URL(request.url).searchParams.get('types')
    const results = types?.includes('transformation')
        ? _hogFunctionTemplatesTransformations
        : types?.includes('destination')
          ? _hogFunctionTemplatesDestinations
          : []

    return HttpResponse.json(results)
}

// Access-Control-Allow-Origin must be an origin (scheme + host + port), not a URL with a path.
// Prefer the Origin header; fall back to deriving the origin from Referer (which often carries a path).
function corsAllowOrigin({ request }: MockResolverInfo): string {
    const origin = request.headers.get('origin')
    if (origin && origin.length) {
        return origin
    }
    const referer = request.headers.get('referer')
    if (referer && referer.length) {
        try {
            return new URL(referer).origin
        } catch {
            // malformed referer — fall through to the default
        }
    }
    return 'http://localhost'
}

function posthogCORSResponse(info: MockResolverInfo): Response {
    return HttpResponse.json('ok', {
        status: 200,
        // some of our tests try to make requests via posthog-js e.g. userLogic calls identify
        // they have to have CORS allowed, or they pass but print noise to the console
        headers: {
            'Access-Control-Allow-Origin': corsAllowOrigin(info),
            'Access-Control-Allow-Credentials': 'true',
            'Access-Control-Allow-Headers': '*',
        },
    })
}

export const defaultMocks: Mocks = {
    get: {
        '/api/projects/:team_id/my_notifications/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/actions/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/annotations/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/event_definitions/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/cohorts/': toPaginatedResponse([MOCK_DEFAULT_COHORT]),
        '/api/environments/:team_id/dashboards/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/alerts/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/hog_functions/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/user_product_list/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/dashboard_templates': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/dashboard_templates/repository/': [],
        '/api/environments/:team_id/external_data_sources/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/notebooks': () => {
            // this was matching on `?contains=query` but that made MSW unhappy and seems unnecessary
            return [
                200,
                {
                    count: 0,
                    results: [],
                },
            ]
        },
        'api/projects/:team/notebooks/recording_comments': {
            results: [],
        },
        '/api/projects/:team_id/groups/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/groups_types/': [],
        '/api/environments/:team_id/groups/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/groups_types/': [],
        '/api/environments/:team_id/insights/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/insights/:insight_id/sharing/': {
            enabled: false,
            access_token: 'foo',
            created_at: '2020-11-11T00:00:00Z',
            settings: {},
        } as SharingConfigurationType,
        '/api/projects/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/property_definitions/': EMPTY_PAGINATED_RESPONSE,
        // Property values endpoints - prevent 'Failed to load property values' error toasts
        '/api/event/values/': [],
        '/api/person/values/': [],
        '/api/group/values/': [],
        '/api/environments/:team_id/sessions/values/': [],
        '/api/projects/:team_id/flag_value/values/': [],
        '/api/projects/:team_id/groups/property_values/': [],
        '/api/environments/:team_id/data_warehouse/property_values/': [],
        '/api/projects/:team_id/feature_flags/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/feature_flags/:feature_flag_id/role_access': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/experiments/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/experiments/eligible_feature_flags/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/experiments/stats/': MOCK_EXPERIMENTS_STATS_RESPONSE,
        '/api/environments/:team_id/warehouse_view_link/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/warehouse_saved_query_folders/': [],
        '/api/environments/:team_id/warehouse_saved_queries/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/warehouse_tables/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/core_memory/': { results: [] },
        '/api/environments/:team_id/conversations/': EMPTY_PAGINATED_RESPONSE,
        '/api/user_home_settings/@me/': { tabs: [], homepage: null },
        '/api/organizations/@current/': () => [
            200,
            {
                ...MOCK_DEFAULT_ORGANIZATION,
                available_product_features: getAvailableProductFeatures(),
            },
        ],
        '/api/organizations/:organization_id/roles/': EMPTY_PAGINATED_RESPONSE,
        '/api/organizations/:organization_id/resource_access': EMPTY_PAGINATED_RESPONSE,
        '/api/organizations/:organization_id/members/': toPaginatedResponse([
            MOCK_DEFAULT_ORGANIZATION_MEMBER,
            MOCK_SECOND_ORGANIZATION_MEMBER,
        ]),
        '/api/organizations/:organization_id/invites/': toPaginatedResponse([MOCK_DEFAULT_ORGANIZATION_INVITE]),
        '/api/organizations/:organization_id/plugins/': toPaginatedResponse([MOCK_DEFAULT_PLUGIN]),
        '/api/organizations/:organization_id/plugins/repository/': [],
        '/api/organizations/:organization_id/plugins/unused/': [],
        '/api/plugin_config/': toPaginatedResponse([MOCK_DEFAULT_PLUGIN_CONFIG]),
        [`/api/environments/:team_id/plugin_configs/${MOCK_DEFAULT_PLUGIN_CONFIG.id}/`]: MOCK_DEFAULT_PLUGIN_CONFIG,
        '/api/environments/:team_id/persons': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/persons/properties/': toPaginatedResponse(MOCK_PERSON_PROPERTIES),
        '/api/personal_api_keys/': [],
        '/api/users/@me/': () => [
            200,
            {
                ...MOCK_DEFAULT_USER,
                organization: {
                    ...MOCK_DEFAULT_ORGANIZATION,
                    available_product_features: getAvailableProductFeatures(),
                },
                pending_invites: [],
            },
        ],
        '/api/users/@me/two_factor_status/': () => [200, { is_enabled: true, backup_codes: [], method: 'TOTP' }],
        '/api/users/@me/hedgehog_config/': {
            color: null,
            enabled: false,
            accessories: ['tophat', 'sunglasses'],
            use_as_profile: true,
            walking_enabled: true,
            controls_enabled: true,
            party_mode_enabled: true,
            interactions_enabled: true,
        },
        '/api/environments/@current/': MOCK_DEFAULT_TEAM, // bootstrap endpoint — intentionally @current
        '/api/projects/@current/': MOCK_DEFAULT_TEAM, // bootstrap endpoint — intentionally @current
        '/api/projects/:team_id/comments/count': { count: 0 },
        '/api/projects/:team_id/comments': { results: [] },
        '/_preflight': _preflight,
        '/api/login/dev': {
            users: [
                { email: 'test@posthog.com', is_staff: true, label: 'Default test user' },
                { email: 'staff@posthog.com', is_staff: true, label: null },
            ],
        },
        '/_system_status': _systemStatus,
        '/api/instance_status': _instanceStatus,
        // TODO: Add a real mock once we know why this endpoint returns an error inside a 200 response
        '/api/sentry_stats/': {
            error: 'Error fetching stats from sentry',
            exception: "[ErrorDetail(string='Sentry integration not configured', code='invalid')]",
        },
        // We don't want to show the "new version available" banner in tests
        'https://api.github.com/repos/posthog/posthog-js/tags': () => [200, []],
        'https://www.gravatar.com/avatar/:gravatar_id': () => [404, ''],
        'https://us.i.posthog.com/api/early_access_features': {
            earlyAccessFeatures: [],
        },
        '/api/billing/': {
            ...billingJson,
        },
        '/api/billing/get_invoices': {
            link: null,
            count: 0,
        },
        '/api/billing/credits/overview': {
            status: 'None',
            eligible: false,
        },

        '/api/billing/spend/': { results: [] },
        '/api/billing/usage/': { results: [] },
        [`${STATUS_PAGE_BASE}/api/v1/summary`]: statusPageAllOK,
        '/api/projects/:team_id/hog_function_templates': hogFunctionTemplatesMock,
        '/api/projects/:team_id/hog_function_templates/:id': hogFunctionTemplateRetrieveMock,
        '/api/projects/:team_id/hog_functions': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/data_color_themes': MOCK_DATA_COLOR_THEMES,
        '/api/projects/:team_id/session_recording_playlists': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/session_recording_playlists': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/session_recordings': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/session_recordings': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/session_recordings/:id/capture_diagnostics': { properties: null },
        '/api/projects/:team_id/insights/my_last_viewed': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/insights/my_last_viewed': EMPTY_PAGINATED_RESPONSE,
        'api/projects/:team_id/early_access_feature': EMPTY_PAGINATED_RESPONSE,
        'api/environments/:team_id/early_access_feature': EMPTY_PAGINATED_RESPONSE,
        '/api/organizations/:organization_id/proxy_records/': [],
        '/api/projects/:team_id/dashboard_templates/json_schema/': EMPTY_PAGINATED_RESPONSE,
        '/api/organizations/:organization_id/domains/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/default_evaluation_contexts/': {
            default_evaluation_contexts: [],
            available_contexts: [],
            hidden_contexts: [],
            enabled: false,
        },
        '/api/environments/:team_id/file_system/unfiled/': { count: 0 },
        '/api/environments/:team_id/file_system/log_view': {},
        '/api/environments/:team_id/file_system': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/file_system_shortcut/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/insight_variables/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/event_ingestion_restrictions/': [],
        'api/projects/:team_id/surveys': EMPTY_PAGINATED_RESPONSE,
        'api/projects/:team_id/surveys/responses_count': {},
        'api/environments/:team_id/integrations': EMPTY_PAGINATED_RESPONSE,
        '/api/organizations/:organization_id/integrations/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/quick_filters/': EMPTY_PAGINATED_RESPONSE,
        'api/environments/:team_id/error_tracking/assignment_rules': EMPTY_PAGINATED_RESPONSE,
        'api/environments/:team_id/error_tracking/grouping_rules': EMPTY_PAGINATED_RESPONSE,
        'api/environments/:team_id/error_tracking/suppression_rules': EMPTY_PAGINATED_RESPONSE,
        'api/environments/:team_id/error_tracking/symbol_sets': EMPTY_PAGINATED_RESPONSE,
        'api/projects/:team_id/resource_access_controls': EMPTY_PAGINATED_RESPONSE,
        'api/projects/:team_id/access_controls': EMPTY_PAGINATED_RESPONSE,
        'api/projects/:team_id/notebooks/recording_comments': EMPTY_PAGINATED_RESPONSE,
        '/api/sdk_versions/': sdkVersions,
        '/api/team_sdk_versions/': teamSdkVersions,
        '/api/environments/:team_id/endpoints/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/signals/source_configs/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/feature_flags/:feature_flag_id/dependent_flags/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/llm_prompts/resolve/': {},
        '/api/environments/:team_id/llm_analytics/': {},
        '/api/projects/:team_id/tags/': [],
    },
    post: {
        'https://us.i.posthog.com/e/': posthogCORSResponse,
        '/e/': posthogCORSResponse,
        'https://us.i.posthog.com/decide/': posthogCORSResponse,
        'https://us.i.posthog.com/flags/': posthogCORSResponse,
        '/decide/': posthogCORSResponse,
        '/flags/': posthogCORSResponse,
        'https://us.i.posthog.com/engage/': posthogCORSResponse,
        '/api/environments/:team_id/query/': [200, { results: [] }],
        '/api/environments/:team_id/query/:query_kind/': [200, { results: [] }],
        '/api/environments/:team_id/insights/viewed/': () => [201, null],
        'api/environments/:team_id/query': [200, { results: [] }],
        'api/environments/:team_id/query/:query_kind/': [200, { results: [] }],
        '/api/environments/:team_id/file_system/log_view/': {},
    },
    patch: {
        '/api/projects/:team_id/session_recording_playlists/:playlist_id/': {},
        '/api/environments/:team_id/add_product_intent/': MOCK_DEFAULT_TEAM,
        '/api/environments/:team_id/': MOCK_DEFAULT_TEAM,
        '/api/user_home_settings/@me/': { tabs: [], homepage: null },
    },
    options: {
        'https://us.i.posthog.com/decide/': posthogCORSResponse,
    },
}
export const handlers = mocksToHandlers(defaultMocks)
