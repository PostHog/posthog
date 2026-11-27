import { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'

import { FEATURE_FLAGS, STORYBOOK_FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { expect, userEvent } from 'storybook/test'

import { ingestionWarningsResponse } from './__mocks__/ingestion-warnings-response'

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Data Management',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-02-15', // To stabilize relative dates
        pageUrl: urls.ingestionWarnings(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/ingestion_warnings/': () => {
                    return [200, ingestionWarningsResponse(dayjs('2023-02-15T16:00:00.000Z'))]
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>
export const IngestionWarnings: Story = {}

export const IngestionWarningsQuill: Story = {
    parameters: {
        featureFlags: [...STORYBOOK_FEATURE_FLAGS, FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { snapshotBrowsers: [] },
    },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const expandButton = await waitFor(() =>
            canvas.getByRole('button', {
                name: 'Show Replay data was dropped because it was too large to ingest warnings',
            })
        )
        await userEvent.click(expandButton)
        await waitFor(() => expect(canvas.getByText(/Session replay data dropped due to its size/)).toBeInTheDocument())
        await expect(
            canvas.getByRole('button', {
                name: 'Hide Replay data was dropped because it was too large to ingest warnings',
            })
        ).toHaveAttribute('aria-expanded', 'true')
    },
}
