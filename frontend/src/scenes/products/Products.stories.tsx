import { Meta, type StoryFn } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'

export default {
    title: 'Scenes-Other/Products',
    component: App,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    realm: 'cloud',
                },
            },
        }),
    ],
} as Meta<typeof App>

const Template: StoryFn<typeof App> = () => {
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingJson,
            },
        },
    })

    useEffect(() => {
        router.actions.push(urls.products())
    }, [])

    return <App />
}

export const DesktopView = Template.bind({})
DesktopView.parameters = {
    testOptions: {
        viewport: {
            width: 2048,
            height: 1024,
        },
    },
}

export const MobileView = Template.bind({})
MobileView.parameters = {
    testOptions: {
        viewport: {
            width: 568,
            height: 1024,
        },
    },
}
