import type { Meta, StoryObj } from '@storybook/react'
import { useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import { PRODUCTS_WITH_SETUP } from 'lib/components/ProductSetup/productSetupRegistry'

import { ProductKey } from '~/queries/schema/schema-general'

import { PostOnboardingModal } from './PostOnboardingModal'
import { postOnboardingModalLogic } from './postOnboardingModalLogic'

interface PostOnboardingModalProps {
    productKey: ProductKey
}

type Story = StoryObj<PostOnboardingModalProps>
const meta: Meta<PostOnboardingModalProps> = {
    title: 'Scenes-Other/Onboarding/Post Onboarding Modal',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
    render: ({ productKey }) => {
        useMountedLogic(postOnboardingModalLogic)
        const { openPostOnboardingModal } = useActions(postOnboardingModalLogic)

        useEffect(() => {
            openPostOnboardingModal(productKey)
        }, [productKey, openPostOnboardingModal])

        return <PostOnboardingModal />
    },
    argTypes: {
        productKey: {
            control: 'select',
            options: PRODUCTS_WITH_SETUP,
        },
    },
}
export default meta

export const ProductAnalytics: Story = { args: { productKey: ProductKey.PRODUCT_ANALYTICS } }

export const WebAnalytics: Story = { args: { productKey: ProductKey.WEB_ANALYTICS } }

export const SessionReplay: Story = { args: { productKey: ProductKey.SESSION_REPLAY } }

export const FeatureFlags: Story = { args: { productKey: ProductKey.FEATURE_FLAGS } }

export const Experiments: Story = { args: { productKey: ProductKey.EXPERIMENTS } }

export const Surveys: Story = { args: { productKey: ProductKey.SURVEYS } }

export const DataWarehouse: Story = { args: { productKey: ProductKey.DATA_WAREHOUSE } }

export const ErrorTracking: Story = { args: { productKey: ProductKey.ERROR_TRACKING } }

export const LLMAnalytics: Story = { args: { productKey: ProductKey.LLM_ANALYTICS } }

export const RevenueAnalytics: Story = { args: { productKey: ProductKey.REVENUE_ANALYTICS } }

export const Logs: Story = { args: { productKey: ProductKey.LOGS } }

export const Workflows: Story = { args: { productKey: ProductKey.WORKFLOWS } }

export const Endpoints: Story = { args: { productKey: ProductKey.ENDPOINTS } }

export const EarlyAccessFeatures: Story = { args: { productKey: ProductKey.EARLY_ACCESS_FEATURES } }
