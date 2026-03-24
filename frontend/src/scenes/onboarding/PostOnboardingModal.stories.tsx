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
    }, [productKey])

    return <PostOnboardingModal />
}

export const Default: StoryFn = Template.bind({})
Default.args = { productKey: ProductKey.PRODUCT_ANALYTICS }
