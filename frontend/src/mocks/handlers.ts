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
} from 'lib/api.mock'

import { ResponseComposition, RestContext, RestRequest } from 'msw'

import { SharingConfigurationType } from '~/types'

import { getAvailableProductFeatures } from './features'
import { billingJson } from './fixtures/_billing'
import _hogFunctionTemplatesDestinations from './fixtures/_hogFunctionTemplatesDestinations.json'
import _hogFunctionTemplatesTransformations from './fixtures/_hogFunctionTemplatesTransformations.json'
import * as statusPageAllOK from './fixtures/_status_page_all_ok.json'
import { MockSignature, Mocks, mocksToHandlers } from './utils'

export const EMPTY_PAGINATED_RESPONSE = { count: 0, results: [] as any[], next: null, previous: null }
export const toPaginatedResponse = (results: any[]): typeof EMPTY_PAGINATED_RESPONSE => ({
    count: results.length,
    results,
    next: null,
    previous: null,
})

const hogFunctionTemplateRetrieveMock: MockSignature = (req, res, ctx) => {
    const hogFunctionTemplate =
        _hogFunctionTemplatesDestinations.results.find((conf) => conf.id === req.params.id) ||
        _hogFunctionTemplatesTransformations.results.find((conf) => conf.id === req.params.id)
    if (!hogFunctionTemplate) {
        return res(ctx.status(404))
    }
    return res(ctx.json({ ...hogFunctionTemplate }))
}

const hogFunctionTemplatesMock: MockSignature = (req, res, ctx) => {
    const results = req.url.searchParams.get('types')?.includes('transformation')
        ? _hogFunctionTemplatesTransformations
        : req.url.searchParams.get('types')?.includes('destination')
          ? _hogFunctionTemplatesDestinations
          : []

    return res(ctx.json(results))
}

// this really returns MaybePromise<ResponseFunction<any>>
// but MSW doesn't export MaybePromise 🤷
function posthogCORSResponse(req: RestRequest, res: ResponseComposition, ctx: RestContext): any {
    return res(
        ctx.status(200),
        ctx.json('ok'),
        // some of our tests try to make requests via posthog-js e.g. userLogic calls identify
        // they have to have CORS allowed, or they pass but print noise to the console
        ctx.set('Access-Control-Allow-Origin', req.referrer.length ? req.referrer : 'http://localhost'),
        ctx.set('Access-Control-Allow-Credentials', 'true'),
        ctx.set('Access-Control-Allow-Headers', '*')
    )
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
        '/api/projects/:team_id/feature_flags/': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/feature_flags/:feature_flag_id/role_access': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/experiments/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/warehouse_view_link/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/warehouse_saved_queries/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/warehouse_tables/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/core_memory/': { results: [] },
        '/api/environments/:team_id/conversations/': EMPTY_PAGINATED_RESPONSE,
        '/api/organizations/@current/': (): MockSignature => [
            200,
            { ...MOCK_DEFAULT_ORGANIZATION, available_product_features: getAvailableProductFeatures() },
        ],
        '/api/organizations/@current/roles/': EMPTY_PAGINATED_RESPONSE,
        '/api/organizations/@current/resource_access': EMPTY_PAGINATED_RESPONSE,
        '/api/organizations/@current/members/': toPaginatedResponse([
            MOCK_DEFAULT_ORGANIZATION_MEMBER,
            MOCK_SECOND_ORGANIZATION_MEMBER,
        ]),
        '/api/organizations/@current/invites/': toPaginatedResponse([MOCK_DEFAULT_ORGANIZATION_INVITE]),
        '/api/organizations/@current/plugins/': toPaginatedResponse([MOCK_DEFAULT_PLUGIN]),
        '/api/organizations/@current/plugins/repository/': [],
        '/api/organizations/@current/plugins/unused/': [],
        '/api/plugin_config/': toPaginatedResponse([MOCK_DEFAULT_PLUGIN_CONFIG]),
        [`/api/environments/:team_id/plugin_configs/${MOCK_DEFAULT_PLUGIN_CONFIG.id}/`]: MOCK_DEFAULT_PLUGIN_CONFIG,
        '/api/environments/:team_id/persons': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/persons/properties/': toPaginatedResponse(MOCK_PERSON_PROPERTIES),
        '/api/personal_api_keys/': [],
        '/api/users/@me/': (): MockSignature => [
            200,
            {
                ...MOCK_DEFAULT_USER,
                organization: {
                    ...MOCK_DEFAULT_ORGANIZATION,
                    available_product_features: getAvailableProductFeatures(),
                },
            },
        ],
        '/api/users/@me/two_factor_status/': () => [200, { is_enabled: true, backup_codes: [], method: 'TOTP' }],
        '/api/users/@me/hedgehog_config/': {
            skin: 'spiderhog',
            color: null,
            enabled: false,
            accessories: ['tophat', 'sunglasses'],
            use_as_profile: true,
            walking_enabled: true,
            controls_enabled: true,
            party_mode_enabled: true,
            interactions_enabled: true,
        },
        '/api/environments/@current/': MOCK_DEFAULT_TEAM,
        '/api/projects/@current/': MOCK_DEFAULT_TEAM,
        '/api/projects/:team_id/comments/count': { count: 0 },
        '/api/projects/:team_id/comments': { results: [] },
        '/_preflight': require('./fixtures/_preflight.json'),
        '/_system_status': require('./fixtures/_system_status.json'),
        '/api/instance_status': require('./fixtures/_instance_status.json'),
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
        'https://status.posthog.com/api/v2/summary.json': statusPageAllOK,
        '/api/projects/:team_id/hog_function_templates': hogFunctionTemplatesMock,
        '/api/projects/:team_id/hog_function_templates/:id': hogFunctionTemplateRetrieveMock,
        '/api/projects/:team_id/hog_functions': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/data_color_themes': MOCK_DATA_COLOR_THEMES,
        '/api/projects/:team_id/session_recording_playlists': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/session_recording_playlists': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/session_recordings': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/session_recordings': EMPTY_PAGINATED_RESPONSE,
        '/api/projects/:team_id/insights/my_last_viewed': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/insights/my_last_viewed': EMPTY_PAGINATED_RESPONSE,
        'api/projects/:team_id/early_access_feature': EMPTY_PAGINATED_RESPONSE,
        'api/environments/:team_id/early_access_feature': EMPTY_PAGINATED_RESPONSE,
        '/api/organizations/:organization_id/proxy_records/': [],
        '/api/projects/:team_id/dashboard_templates/json_schema/': EMPTY_PAGINATED_RESPONSE,
        '/api/organizations/:organization_id/domains/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/file_system/unfiled/': { count: 0 },
        '/api/environments/:team_id/file_system': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/file_system_shortcut/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/insight_variables/': EMPTY_PAGINATED_RESPONSE,
        '/api/environments/:team_id/event_ingestion_restrictions/': [],
        '/api/projects/:team_id/persisted_folder/': EMPTY_PAGINATED_RESPONSE,
        'api/projects/:team_id/surveys': EMPTY_PAGINATED_RESPONSE,
        'api/projects/:team_id/surveys/responses_count': {},
        'api/environments/:team_id/integrations': EMPTY_PAGINATED_RESPONSE,
        'api/environments/:team_id/error_tracking/assignment_rules': EMPTY_PAGINATED_RESPONSE,
        'api/environments/:team_id/error_tracking/grouping_rules': EMPTY_PAGINATED_RESPONSE,
        'api/environments/:team_id/error_tracking/suppression_rules': EMPTY_PAGINATED_RESPONSE,
        'api/environments/:team_id/error_tracking/symbol_sets': EMPTY_PAGINATED_RESPONSE,
        'api/projects/@current/resource_access_controls': EMPTY_PAGINATED_RESPONSE,
        'api/projects/@current/access_controls': EMPTY_PAGINATED_RESPONSE,
        'api/projects/:team_id/notebooks/recording_comments': EMPTY_PAGINATED_RESPONSE,
    },
    post: {
        'https://us.i.posthog.com/e/': (req, res, ctx): MockSignature => posthogCORSResponse(req, res, ctx),
        '/e/': (req, res, ctx): MockSignature => posthogCORSResponse(req, res, ctx),
        'https://us.i.posthog.com/decide/': (req, res, ctx): MockSignature => posthogCORSResponse(req, res, ctx),
        'https://us.i.posthog.com/flags/': (req, res, ctx): MockSignature => posthogCORSResponse(req, res, ctx),
        '/decide/': (req, res, ctx): MockSignature => posthogCORSResponse(req, res, ctx),
        '/flags/': (req, res, ctx): MockSignature => posthogCORSResponse(req, res, ctx),
        'https://us.i.posthog.com/engage/': (req, res, ctx): MockSignature => posthogCORSResponse(req, res, ctx),
        '/api/environments/:team_id/insights/viewed/': (): MockSignature => [201, null],
        'api/environments/:team_id/query': [200, { results: [] }],
    },
    patch: {
        '/api/projects/:team_id/session_recording_playlists/:playlist_id/': {},
        '/api/environments/:team_id/': MOCK_DEFAULT_TEAM,
    },
    options: {
        'https://us.i.posthog.com/decide/': (req, res, ctx): MockSignature => posthogCORSResponse(req, res, ctx),
    },
}
export const handlers = mocksToHandlers(defaultMocks)
