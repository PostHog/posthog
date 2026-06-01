import { Decorator, Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import {
    errorTrackingEventsQueryResponse,
    errorTrackingQueryResponse,
    errorTrackingTypeIssue,
} from 'products/error_tracking/frontend/__mocks__/error_tracking_query'

// Seeding the persisted value before <App /> mounts lets panelLayoutLogic initialise in the
// desired state without mounting the logic early in a decorator, which would hijack routing.
const NAV_COLLAPSED_STORAGE_KEY = 'layout.panel-layout.panelLayoutLogic.isLayoutNavCollapsedDesktop'

const withNavCollapsed = (collapsed: boolean): Decorator => {
    return function WithNavCollapsed(Story) {
        window.localStorage.setItem(NAV_COLLAPSED_STORAGE_KEY, JSON.stringify(collapsed))
        return <Story />
    }
}

const meta: Meta<typeof App> = {
    component: App,
    title: 'Scenes-App/Navigation',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-07-09',
        pageUrl: urls.errorTracking(),
        testOptions: {
            includeNavigationInSnapshot: true,
            viewportWidths: ['wide'],
        },
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/error_tracking/issue/:id': async (_, res, ctx) => {
                    return res(ctx.json(errorTrackingTypeIssue))
                },
            },
            post: {
                '/api/environments/:team_id/query/ErrorTrackingQuery': async (_, res, ctx) =>
                    res(ctx.json(errorTrackingQueryResponse)),
                '/api/environments/:team_id/query/EventsQuery': async (_, res, ctx) =>
                    res(ctx.json(errorTrackingEventsQueryResponse)),
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof App>

export const Expanded: Story = {
    decorators: [withNavCollapsed(false)],
}

export const Collapsed: Story = {
    decorators: [withNavCollapsed(true)],
}
