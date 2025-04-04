import { Meta, StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

const meta: Meta = {
    title: 'Scenes-App/SessionAttributionExplorer',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2022-03-11',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/query/:id/': async (_, res, ctx) => {
                    // eslint-disable-next-line @typescript-eslint/no-var-requires
                    return res(ctx.json(require('./__mocks__/sessionAttributionQueryStatus.json')))
                },
            },
            post: {
                '/api/projects/:team_id/query/': async (_, res, ctx) => {
                    // eslint-disable-next-line @typescript-eslint/no-var-requires
                    return res(ctx.json(require('./__mocks__/sessionAttributionQuery.json')))
                },
            },
        }),
    ],
}
export default meta

// Session Attribution Explorer
export const SessionAttributionExplorer: StoryFn = () => {
    useEffect(() => {
        router.actions.push(urls.sessionAttributionExplorer())
    }, [])
    return <App />
}
SessionAttributionExplorer.parameters = {
    testOptions: { waitForSelector: '.LemonTable__boundary' },
}
