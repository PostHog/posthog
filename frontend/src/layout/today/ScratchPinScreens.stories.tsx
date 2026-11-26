import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import featureFlags from 'scenes/feature-flags/__mocks__/feature_flags.json'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const EVENT = {
    id: '1',
    name: 'signup_clicked',
    description: 'When a visitor clicks the signup button',
    tags: [],
    last_seen_at: '2026-04-29T18:00:00Z',
    last_updated_at: '2026-04-29T18:00:00Z',
    created_at: '2025-01-01T00:00:00Z',
    updated_at: '2026-04-15T10:00:00Z',
    verified: false,
    hidden: false,
    media_preview_urls: [],
    is_action: false,
    is_calculating: false,
    last_calculated_at: null,
    enforcement_mode: 'allow',
    post_to_slack: false,
    default_columns: [],
    owner: null,
    created_by: null,
}

const BASE_FLAG = featureFlags.results.find((f) => f.id === 1779)!
const FLAG = { ...BASE_FLAG, key: 'new-checkout-flow', name: 'Roll out the new checkout flow', can_edit: true }

const fileSystemList = ({ request }: { request: Request }): [number, any] => {
    const url = new URL(request.url)
    if (url.searchParams.get('type') === 'feature_flag' && url.searchParams.get('ref') === String(FLAG.id)) {
        return [
            200,
            {
                count: 1,
                next: null,
                previous: null,
                users: [],
                results: [
                    {
                        id: '0190c3a1-1f2e-7000-8000-00000000f1a9',
                        path: 'Unfiled/Feature Flags/new-checkout-flow',
                        type: 'feature_flag',
                        ref: String(FLAG.id),
                        href: urls.featureFlag(FLAG.id),
                        created_at: '2026-01-01T00:00:00Z',
                        meta: {},
                    },
                ],
            },
        ]
    }
    return [200, { count: 0, next: null, previous: null, results: [], users: [] }]
}

const meta: Meta = {
    component: App,
    title: 'Scratch/Pin screens',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-04-30',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.DATA_AREA, FEATURE_FLAGS.RELEASES_AREA],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:project_id/event_definitions/:id/': EVENT,
                '/api/projects/:project_id/event_definitions/:id/metrics/': { query_usage_30_day: 42 },
                '/api/projects/:project_id/event_definitions/primary_properties/': { primary_properties: {} },
                '/api/projects/:project_id/object_media_previews/': [],
                '/api/projects/:project_id/experiments/': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:project_id/insights/': { count: 0, next: null, previous: null, results: [] },
                '/api/projects/:team_id/feature_flags/:flagId/': FLAG,
                '/api/projects/:team_id/feature_flags/:flagId/status': {
                    status: 'active',
                    reason: 'Feature flag is active',
                },
                '/api/environments/:team_id/file_system': fileSystemList,
                '/api/environments/:team_id/file_system/': fileSystemList,
                '/api/projects/:team_id/file_system': fileSystemList,
                '/api/projects/:team_id/file_system/': fileSystemList,
            },
            post: {
                '/api/environments/:team_id/query/:kind': {},
                '/api/projects/:team_id/feature_flags/user_blast_radius/': () => [200, { affected: 120, total: 2000 }],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const EventDefinition: Story = { parameters: { pageUrl: urls.eventDefinition(EVENT.id) } }
export const FeatureFlag: Story = { parameters: { pageUrl: urls.featureFlag(FLAG.id) } }
