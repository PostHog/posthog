import { Meta, StoryObj } from '@storybook/react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import sessionAttributionQuery from './__mocks__/sessionAttributionQuery.json'
import sessionAttributionQueryStatus from './__mocks__/sessionAttributionQueryStatus.json'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/SessionAttributionExplorer',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2022-03-11',
        pageUrl: urls.sessionAttributionExplorer(),
        testOptions: { waitForSelector: '.LemonTable__boundary' },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/query/:id/': async (_, res, ctx) => {
                    return res(ctx.json(sessionAttributionQueryStatus))
                },
            },
            post: {
                '/api/environments/:team_id/query/': async (_, res, ctx) => {
                    return res(ctx.json(sessionAttributionQuery))
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const SessionAttributionExplorer: Story = {}
