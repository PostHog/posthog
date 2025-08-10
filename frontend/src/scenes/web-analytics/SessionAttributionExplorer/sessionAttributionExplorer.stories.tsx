import { Meta, StoryObj } from '@storybook/react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

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
                    // eslint-disable-next-line @typescript-eslint/no-var-requires
                    return res(ctx.json(require('./__mocks__/sessionAttributionQueryStatus.json')))
                },
            },
            post: {
                '/api/environments/:team_id/query/': async (_, res, ctx) => {
                    // eslint-disable-next-line @typescript-eslint/no-var-requires
                    return res(ctx.json(require('./__mocks__/sessionAttributionQuery.json')))
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const SessionAttributionExplorer: Story = {}
