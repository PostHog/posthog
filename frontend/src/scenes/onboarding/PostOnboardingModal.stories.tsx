import { Meta, StoryFn } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { PRODUCTS_WITH_SETUP } from 'lib/components/ProductSetup/productSetupRegistry'

import { ProductKey } from '~/queries/schema/schema-general'

import { PostOnboardingModal } from './PostOnboardingModal'
import { postOnboardingModalLogic } from './postOnboardingModalLogic'

const meta: Meta = {
    title: 'Scenes-Other/Onboarding/Post Onboarding Modal',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    argTypes: {
        productKey: {
            control: 'select',
            options: PRODUCTS_WITH_SETUP,
        },
    },
}
export default meta

const Template: StoryFn<{ productKey: ProductKey }> = ({ productKey }) => {
    useMountedLogic(postOnboardingModalLogic)
    const { openPostOnboardingModal } = useActions(postOnboardingModalLogic)

    useEffect(() => {
        openPostOnboardingModal(productKey)
    }, [productKey, openPostOnboardingModal])

    return <PostOnboardingModal />
}

export const ProductAnalytics: StoryFn<{ productKey: ProductKey }> = Template.bind({})
ProductAnalytics.args = { productKey: ProductKey.PRODUCT_ANALYTICS }

export const WebAnalytics: StoryFn<{ productKey: ProductKey }> = Template.bind({})
WebAnalytics.args = { productKey: ProductKey.WEB_ANALYTICS }

export const SessionReplay: StoryFn<{ productKey: ProductKey }> = Template.bind({})
SessionReplay.args = { productKey: ProductKey.SESSION_REPLAY }

export const FeatureFlags: StoryFn<{ productKey: ProductKey }> = Template.bind({})
FeatureFlags.args = { productKey: ProductKey.FEATURE_FLAGS }

export const Experiments: StoryFn<{ productKey: ProductKey }> = Template.bind({})
Experiments.args = { productKey: ProductKey.EXPERIMENTS }

export const Surveys: StoryFn<{ productKey: ProductKey }> = Template.bind({})
Surveys.args = { productKey: ProductKey.SURVEYS }

export const DataWarehouse: StoryFn<{ productKey: ProductKey }> = Template.bind({})
DataWarehouse.args = { productKey: ProductKey.DATA_WAREHOUSE }

export const ErrorTracking: StoryFn<{ productKey: ProductKey }> = Template.bind({})
ErrorTracking.args = { productKey: ProductKey.ERROR_TRACKING }

export const LLMAnalytics: StoryFn<{ productKey: ProductKey }> = Template.bind({})
LLMAnalytics.args = { productKey: ProductKey.LLM_ANALYTICS }

export const RevenueAnalytics: StoryFn<{ productKey: ProductKey }> = Template.bind({})
RevenueAnalytics.args = { productKey: ProductKey.REVENUE_ANALYTICS }

export const Logs: StoryFn<{ productKey: ProductKey }> = Template.bind({})
Logs.args = { productKey: ProductKey.LOGS }

export const Workflows: StoryFn<{ productKey: ProductKey }> = Template.bind({})
Workflows.args = { productKey: ProductKey.WORKFLOWS }

export const Endpoints: StoryFn<{ productKey: ProductKey }> = Template.bind({})
Endpoints.args = { productKey: ProductKey.ENDPOINTS }

export const EarlyAccessFeatures: StoryFn<{ productKey: ProductKey }> = Template.bind({})
EarlyAccessFeatures.args = { productKey: ProductKey.EARLY_ACCESS_FEATURES }
