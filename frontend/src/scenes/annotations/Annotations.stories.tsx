import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import annotations from './__mocks__/annotations.json'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Annotations',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-01-28', // To stabilize relative dates
        pageUrl: urls.annotations(),
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

type Story = StoryObj<{}>
// The table renders the emoji next to the content for annotations that have one (see the fixture).
export const Annotations: Story = {}

// Opening an annotation that has an emoji surfaces the populated emoji picker in the edit modal.
export const EditAnnotationWithEmoji: Story = {
    parameters: {
        pageUrl: urls.annotation(114064),
        testOptions: { waitForSelector: '.LemonModal' },
    },
}
