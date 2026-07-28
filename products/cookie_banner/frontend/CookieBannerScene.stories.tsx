import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { CookieBannerConfigApi } from './generated/api.schemas'

const CONFIG_RESULT: CookieBannerConfigApi = {
    id: '0187c22c-06d9-0000-34fe-daa2e2afb503',
    enabled: true,
    appearance: {
        title: 'We use cookies',
        artStyle: 'hedgehog-builder',
    },
    created_at: '2023-04-27T11:29:30.798968Z',
    updated_at: '2023-04-27T11:29:30.798968Z',
    created_by: {
        id: 123456,
        uuid: '0187c22c-06d9-0000-34fe-daa2e2afb504',
        distinct_id: '0187c22c-06d9-0000-34fe-daa2e2afb505',
        first_name: 'John',
        email: 'john@example.com',
        hedgehog_config: null,
    },
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/CookieBanner',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
        pageUrl: urls.cookieBanner(),
        featureFlags: [FEATURE_FLAGS.COOKIE_BANNER],
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/cookie_banner': {
                    count: 1,
                    results: [CONFIG_RESULT] as any[],
                    next: null,
                    previous: null,
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const CookieBannerSettings: Story = {}
