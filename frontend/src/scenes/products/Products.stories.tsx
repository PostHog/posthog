import { Meta } from '@storybook/react'
import { useFeatureFlags, useStorybookMocks } from '~/mocks/browser'
import { FEATURE_FLAGS } from 'lib/constants'
import { useEffect } from 'react'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import { App } from 'scenes/App'
import billingJson from '~/mocks/fixtures/_billing_v2.json'

const meta: Meta = {
    title: 'Scenes-App/Products',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta
export const ProductsScene = (): JSX.Element => {
    useFeatureFlags([[FEATURE_FLAGS.PRODUCT_SPECIFIC_ONBOARDING, 'test']])
    useStorybookMocks({
        get: {
            '/api/billing-v2/': {
                ...billingJson,
            },
        },
    })
    useEffect(() => {
        router.actions.push(urls.products())
    }, [])

    return <App />
}
