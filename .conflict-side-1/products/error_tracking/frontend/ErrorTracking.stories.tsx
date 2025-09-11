import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { NodeKind } from '~/queries/schema/schema-general'

import {
    errorTrackingEventsQueryResponse,
    errorTrackingQueryResponse,
    errorTrackingTypeIssue,
} from './__mocks__/error_tracking_query'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/ErrorTracking',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-07-09', // To stabilize relative dates
        pageUrl: urls.errorTracking(),
    },
    decorators: [
        mswDecorator({
            get: {
                'api/projects/:team_id/error_tracking/issue/:id': async (_, res, ctx) => {
                    return res(ctx.json(errorTrackingTypeIssue))
                },
            },
            post: {
                '/api/environments/:team_id/query': async (req, res, ctx) => {
                    const query = (await req.clone().json()).query
                    if (query.kind === NodeKind.ErrorTrackingQuery) {
                        return res(ctx.json(errorTrackingQueryResponse))
                    }
                    return res(ctx.json(errorTrackingEventsQueryResponse))
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const ListPage: Story = {}
export const GroupPage: Story = { parameters: { pageUrl: urls.errorTrackingIssue('id') } }
