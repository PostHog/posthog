import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import annotations from './__mocks__/annotations.json'

const meta: Meta = {
    title: 'Scenes-App/Annotations',
    parameters: {
        layout: 'fullscreen',
        testOptions: {
            excludeNavigationFromSnapshot: true,
        },
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/annotations/': annotations,
                '/api/projects/:team_id/annotations/:annotationId/': (req) => [
                    200,
                    annotations.results.find((r) => r.id === Number(req.params['annotationId'])),
                ],
            },
        }),
    ],
}
export default meta
export const Annotations = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.annotations())
    }, [])
    return <App />
}
