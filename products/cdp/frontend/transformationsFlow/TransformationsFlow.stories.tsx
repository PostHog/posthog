import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { MockResolverInfo } from '~/mocks/utils'

const BUILDER_HOG_ICON = 'https://res.cloudinary.com/dmukukwp6/image/upload/q_auto,f_auto/builder_hog_01_955c082cad.png'

const GEOIP_ID = '0196b144-1f82-0000-0d0d-a01de54d6701'
const IP_ANONYMIZATION_ID = '0196b144-1f82-0000-0d0d-a01de54d6703'

const transformation = (
    id: string,
    name: string,
    description: string,
    execution_order: number,
    enabled: boolean,
    icon_url: string
): Record<string, unknown> => ({
    id,
    name,
    description,
    type: 'transformation',
    enabled,
    execution_order,
    hog: 'return event',
    inputs_schema: [],
    inputs: {},
    filters: {},
    icon_url,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-18T14:00:00Z',
})

const TRANSFORMATIONS = [
    transformation(
        GEOIP_ID,
        'GeoIP',
        'Adds geolocation properties from the IP address',
        1,
        true,
        '/static/transformations/geoip.png'
    ),
    transformation(
        '0196b144-1f82-0000-0d0d-a01de54d6702',
        'URL parameter masking',
        'Masks sensitive query parameters in URLs',
        2,
        true,
        BUILDER_HOG_ICON
    ),
    transformation(
        IP_ANONYMIZATION_ID,
        'IP anonymization',
        'Sets the last octet of the IP address to zero',
        3,
        true,
        BUILDER_HOG_ICON
    ),
    transformation(
        '0196b144-1f82-0000-0d0d-a01de54d6704',
        'Bot detection',
        'Drops events from known bots',
        4,
        false,
        BUILDER_HOG_ICON
    ),
]

// Gives each transformation a visible effect, so a person can step through the test in this story.
const testInvocation = async ({ request, params }: MockResolverInfo): Promise<Record<string, unknown>> => {
    const body = (await request.json()) as { globals: { event: Record<string, any> } }
    const event = body.globals.event
    if (params.id === GEOIP_ID) {
        return {
            status: 'success',
            logs: [],
            result: {
                ...event,
                properties: { ...event.properties, $geoip_country_name: 'Sweden', $geoip_city_name: 'Linköping' },
            },
        }
    }
    if (params.id === IP_ANONYMIZATION_ID) {
        return {
            status: 'success',
            logs: [],
            result: { ...event, properties: { ...event.properties, $ip: '89.160.20.0' } },
        }
    }
    return { status: 'success', logs: [], result: event }
}

const EVENT_FILTER = {
    id: '0196b144-1f82-0000-0d0d-a01de54d6710',
    mode: 'live',
    filter_tree: {
        type: 'or',
        children: [
            { type: 'condition', field: 'event_name', operator: 'exact', value: '$internal_ping' },
            { type: 'condition', field: 'distinct_id', operator: 'contains', value: 'bot-' },
        ],
    },
    test_cases: [
        { event_name: '$internal_ping', distinct_id: 'user-1', expected_result: 'drop' },
        { event_name: '$pageview', distinct_id: 'bot-crawler', expected_result: 'drop' },
        { event_name: '$pageview', distinct_id: 'user-1', expected_result: 'ingest' },
    ],
}

// Updates are kept, so that the next read returns the saved state, the same as the real API.
const savedTransformations = new Map(TRANSFORMATIONS.map((item) => [item.id as string, item]))

const getTransformation = ({ params }: MockResolverInfo): Record<string, unknown> | [number, unknown] =>
    savedTransformations.get(params.id as string) ?? [404, { detail: 'Not found' }]

// The backend puts a transformation that is enabled again after all the others.
const updateTransformation = async ({ request, params }: MockResolverInfo): Promise<Record<string, unknown>> => {
    const body = (await request.json()) as { enabled?: boolean }
    const updated = {
        ...savedTransformations.get(params.id as string),
        ...body,
        ...(body.enabled ? { execution_order: TRANSFORMATIONS.length + 1 } : {}),
    }
    savedTransformations.set(params.id as string, updated)
    return updated
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data pipelines/Transformations flow',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: `${urls.transformations()}?view=flow`,
        mockDate: '2026-08-21',
        featureFlags: [FEATURE_FLAGS.TRANSFORMATIONS_FLOW_VIEW],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/hog_functions/': {
                    count: TRANSFORMATIONS.length,
                    results: TRANSFORMATIONS,
                    next: null,
                },
                '/api/projects/:team_id/hog_functions/': {
                    count: TRANSFORMATIONS.length,
                    results: TRANSFORMATIONS,
                    next: null,
                },
                '/api/projects/:team_id/hog_functions/:id/': getTransformation,
                '/api/environments/:team_id/hog_functions/:id/': getTransformation,
                '/api/projects/:team_id/event_filter/': EVENT_FILTER,
                '/api/environments/:team_id/event_filter/': EVENT_FILTER,
            },
            patch: {
                '/api/projects/:team_id/hog_functions/:id/': updateTransformation,
                '/api/environments/:team_id/hog_functions/:id/': updateTransformation,
            },
            post: {
                '/api/environments/:team_id/hog_functions/:id/invocations/': testInvocation,
                '/api/projects/:team_id/hog_functions/:id/invocations/': testInvocation,
                '/api/environments/:team_id/query/:kind/': { results: [] },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

// Three enabled transformations between the fixed ingestion steps, and one disabled transformation
// in a separate column outside the flow.
export const Default: Story = {}
