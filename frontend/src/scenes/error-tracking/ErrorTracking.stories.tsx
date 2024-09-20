import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { NodeKind } from '~/queries/schema'

import { errorTrackingEventsQueryResponse, errorTrackingQueryResponse } from './__mocks__/error_tracking_query'
import { stringifiedFingerprint } from './utils'

const meta: Meta = {
    title: 'Scenes-App/ErrorTracking',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-07-09', // To stabilize relative dates
    },
    decorators: [
        mswDecorator({
            post: {
                '/api/projects/:team_id/query': async (req, res, ctx) => {
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
export function ListPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.errorTracking())
    }, [])
    return <App />
}

export function GroupPage(): JSX.Element {
    useEffect(() => {
        router.actions.push(urls.errorTrackingGroup(stringifiedFingerprint(['TypeError'])))
    }, [])
    return <App />
}
