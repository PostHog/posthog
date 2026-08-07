import { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { urls } from 'scenes/urls'

import { useStorybookMocks } from '~/mocks/browser'

import preflightJson from '../../../mocks/fixtures/_preflight.json'
import { ConfirmOrganization } from './ConfirmOrganization'

const meta: Meta = {
    title: 'Scenes-Other/ConfirmOrganization',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta

type Story = StoryObj<{}>

const CLOUD_PREFLIGHT = {
    ...preflightJson,
    cloud: true,
    region: 'US',
    realm: 'cloud',
    can_create_org: true,
}

const CONFIRM_CREATION_URL = `${urls.organizationCreationConfirm()}?organization_name=&first_name=Jane&email=jane%40example.com`

export const ActiveSession: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/_preflight': CLOUD_PREFLIGHT,
                '/api/social_signup/': { active: true },
            },
        })
        useDelayedOnMountEffect(() => router.actions.push(CONFIRM_CREATION_URL))
        return <ConfirmOrganization />
    },
}

export const InactiveSessionRecovery: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/_preflight': CLOUD_PREFLIGHT,
                '/api/social_signup/': { active: false },
            },
        })
        useDelayedOnMountEffect(() => router.actions.push(CONFIRM_CREATION_URL))
        return <ConfirmOrganization />
    },
}
