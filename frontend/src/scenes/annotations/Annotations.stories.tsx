import { useEffect } from 'react'
import { Meta } from '@storybook/react'
import { App } from 'scenes/App'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { mswDecorator } from '~/mocks/browser'
import annotations from './__mocks__/annotations.json'

export default {
    title: 'Scenes-App/Annotations',
    parameters: {
        layout: 'fullscreen',
        options: { showPanel: false },
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
} as Meta

export const Annotations = (): JSX.Element => {
    useEffect(() => {
        router.actions.push(urls.annotations())
    }, [])
    return <App />
}
