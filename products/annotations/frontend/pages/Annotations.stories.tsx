import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS, STORYBOOK_FEATURE_FLAGS } from 'lib/constants'
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
        testOptions: { viewport: { width: 1300, height: 2000 } },
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/annotations/': annotations,
                '/api/projects/:team_id/annotations/:annotationId/': ({ params }) => [
                    200,
                    annotations.results.find((r) => r.id === Number(params['annotationId'])),
                ],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
// The table renders the emoji next to the content for annotations that have one (see the fixture),
// giving visual-regression coverage of the emoji display.
export const Annotations: Story = {}

const openNewAnnotationModal: Story['play'] = async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.click(await canvas.findByText('New annotation'))
}

export const NewAnnotationModalLemonUIDatePicker: Story = {
    play: openNewAnnotationModal,
}

export const NewAnnotationModalQuillDatePicker: Story = {
    parameters: { featureFlags: [FEATURE_FLAGS.QUILL_DATE_PICKER] },
    play: openNewAnnotationModal,
}

const QUILL_FLAGS = [...STORYBOOK_FEATURE_FLAGS, FEATURE_FLAGS.TODAY_RAIL_NAV]

export const AnnotationsQuill: Story = {
    parameters: {
        featureFlags: QUILL_FLAGS,
        testOptions: { waitForSelector: '[data-attr="annotations-table"]', snapshotBrowsers: [] },
    },
}

export const NewAnnotationModalQuill: Story = {
    parameters: {
        featureFlags: QUILL_FLAGS,
        testOptions: { waitForSelector: '[data-attr="annotations-table"]', snapshotBrowsers: [] },
    },
    play: async (context) => {
        await openNewAnnotationModal(context)
        const body = within(context.canvasElement.ownerDocument.body)
        await body.findByRole('dialog', { name: 'New annotation' })
        await userEvent.type(await body.findByPlaceholderText("What's this annotation about?"), 'Launched pricing page')
    },
}
