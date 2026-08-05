import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import __sessionAttributionQuery from './__mocks__/sessionAttributionQuery.json'
import __sessionAttributionQueryStatus from './__mocks__/sessionAttributionQueryStatus.json'

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
                '/api/environments/:team_id/query/:id/': () => {
                    // eslint-disable-next-line @typescript-eslint/no-var-requires
                    return [200, __sessionAttributionQueryStatus as any]
                },
            },
            post: {
                '/api/environments/:team_id/query/:kind/': () => {
                    // eslint-disable-next-line @typescript-eslint/no-var-requires
                    return [200, __sessionAttributionQuery as any]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const SessionAttributionExplorer: Story = {}
