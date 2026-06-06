import { Meta, StoryObj } from '@storybook/react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { userLogic } from 'scenes/userLogic'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { ConfirmOrganization } from './ConfirmOrganization'
import { confirmOrganizationLogic } from './confirmOrganizationLogic'

const meta: Meta = {
    title: 'Scenes-Other/ConfirmOrganization',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        testOptions: {
            waitForSelector: '.BridgePage__left__message--visible',
        },
    },
    decorators: [
        mswDecorator({
            get: { '/api/users/@me': () => [500, null] },
            post: {
                '/api/social_signup/': (_, __, ctx) => [ctx.delay(1000), ctx.status(200), ctx.json({ success: true })],
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

export const Default: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    realm: 'cloud',
                },
            },
        })

        useDelayedOnMountEffect(() => {
            userLogic.actions.loadUserSuccess(null)
            confirmOrganizationLogic.actions.setEmail('jane@hogflix.com')
        })

        return <ConfirmOrganization />
    },
}
