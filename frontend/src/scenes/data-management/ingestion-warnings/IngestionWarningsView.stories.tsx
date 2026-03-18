import { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

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

type Story = StoryObj<typeof meta>
export const IngestionWarnings: Story = {}
