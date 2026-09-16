import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const NEEDS_CREDENTIALS_ID = '0196b144-1f82-0000-0d0d-a01de54d674d'
const REPLAYABLE_ID = '0196b144-1f82-0000-0d0d-a01de54d6750'

const hogFunction = (id: string, name: string): Record<string, unknown> => ({
    id,
    name,
    type: 'destination',
    enabled: true,
    inputs_schema: [{ key: 'api_key', type: 'string', label: 'API key', secret: true }],
    inputs: {},
    filters: {},
    icon_url: null,
    created_at: '2026-08-01T00:00:00Z',
    updated_at: '2026-08-18T14:00:00Z',
})

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data pipelines/Destinations incident replay banner',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.destinations(),
        mockDate: '2026-08-21',
        featureFlags: [FEATURE_FLAGS.DESTINATIONS_INCIDENT_REPLAY],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_functions/masked_secrets/': [
                    {
                        id: NEEDS_CREDENTIALS_ID,
                        name: 'Customer.io',
                        type: 'destination',
                        enabled: true,
                        input_keys: ['api_key'],
                        draft_input_keys: [],
                    },
                ],
                [`/api/projects/:team_id/hog_functions/${NEEDS_CREDENTIALS_ID}/`]: hogFunction(
                    NEEDS_CREDENTIALS_ID,
                    'Customer.io'
                ),
                [`/api/projects/:team_id/hog_functions/${REPLAYABLE_ID}/`]: hogFunction(REPLAYABLE_ID, 'HubSpot'),
                '/api/projects/:team_id/hog_functions/': {
                    count: 2,
                    results: [hogFunction(NEEDS_CREDENTIALS_ID, 'Customer.io'), hogFunction(REPLAYABLE_ID, 'HubSpot')],
                    next: null,
                },
            },
            post: {
                '/api/environments/:team_id/query/:query_kind/': {
                    results: [
                        [REPLAYABLE_ID, 12480],
                        [NEEDS_CREDENTIALS_ID, 3106],
                    ],
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

// One destination still storing the mask and one already fixed, which is what the banner has to
// tell apart: the first can only be sent to its configuration, the second can be replayed.
export const Default: Story = {}
