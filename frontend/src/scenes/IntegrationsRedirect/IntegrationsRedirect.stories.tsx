import { Meta, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { mswDecorator } from '~/mocks/browser'

import { IntegrationsRedirect } from './IntegrationsRedirect'

const meta: Meta<typeof IntegrationsRedirect> = {
    title: 'Scenes-Other/Integrations redirect',
    component: IntegrationsRedirect,
    parameters: { layout: 'fullscreen', viewMode: 'story' },
    decorators: [mswDecorator({ get: { '/api/environments/:id/integrations': { results: [] } } })],
}
export default meta

type Story = StoryObj<typeof IntegrationsRedirect>

// The callback stalled: the scene stops spinning and offers a way back to integration settings.
export const TimedOut: Story = {
    decorators: [
        function TimedOut(Story): JSX.Element {
            useEffect(() => {
                integrationsLogic.mount()
                integrationsLogic.actions.setOauthCallbackTimedOut()
            }, [])
            return <Story />
        },
    ],
}
