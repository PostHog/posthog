import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import preflightJson from '../mocks/fixtures/_preflight.json'
import { ErrorProjectAccessDenied } from './ErrorProjectAccessDenied'

const meta: Meta<typeof ErrorProjectAccessDenied> = {
    title: 'Scenes-App/Error Project Access Denied',
    component: ErrorProjectAccessDenied,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj<typeof ErrorProjectAccessDenied>

export const SelfHosted: Story = {}

export const Cloud: Story = {
    decorators: [mswDecorator({ get: { '/_preflight': { ...preflightJson, cloud: true, region: 'EU' } } })],
}
