import { Meta } from '@storybook/react'
import { router } from 'kea-router'
import { useEffect } from 'react'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'

const meta: Meta = {
    title: 'Scenes-Other/Products',
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
}
export default meta
export const _Products = (): JSX.Element => {
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
