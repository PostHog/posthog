import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'

import { mswDecorator } from '~/mocks/browser'

const meta: Meta = {
    title: 'Products/Business intelligence/Worksheets',
    component: App,
    decorators: [mswDecorator({})],
    parameters: {
        layout: 'fullscreen',
        pageUrl: '/bi',
        featureFlags: [FEATURE_FLAGS.SQL_EDITOR_BI_MODE],
        testOptions: { waitForSelector: '[data-attr="bi-worksheet-link"]' },
        msw: {
            mocks: {
                get: {
                    '/api/projects/:team_id/insights/': {
                        count: 2,
                        results: [
                            {
                                id: 1,
                                short_id: 'revenue',
                                name: 'Revenue by country',
                                last_modified_at: '2026-01-01T12:00:00Z',
                            },
                            {
                                id: 2,
                                short_id: 'activity',
                                name: 'Weekly activity',
                                last_modified_at: '2026-01-01T10:00:00Z',
                            },
                        ],
                    },
                },
            },
        },
    },
}
export default meta
export const Worksheets: StoryObj = {}
