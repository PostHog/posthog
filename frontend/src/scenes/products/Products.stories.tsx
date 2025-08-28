import { Meta, StoryObj } from '@storybook/react'

import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'

const meta: Meta = {
    component: App,
    title: 'Scenes-Other/Products',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
        pageUrl: urls.products(),
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/billing/': { ...billingJson },
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    realm: 'cloud',
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<typeof meta>
export const DesktopView: Story = {
    parameters: {
        testOptions: {
            viewport: {
                width: 2048,
                height: 1024,
            },
        },
    },
}

export const MobileView: Story = {
    parameters: {
        testOptions: {
            viewport: {
                width: 568,
                height: 1024,
            },
        },
    },
}
