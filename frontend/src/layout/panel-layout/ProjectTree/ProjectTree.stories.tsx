import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { setFeatureFlags } from '~/mocks/browser'

import { ProjectTree, ProjectTreeProps } from './ProjectTree'

interface StoryProps extends ProjectTreeProps {
    enableCustomProductsFlag?: boolean
}

type Story = StoryObj<(props: StoryProps) => JSX.Element>

const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Layout/Project Tree/Custom Products',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        featureFlags: [
            FEATURE_FLAGS.CUSTOM_PRODUCTS_SIDEBAR,
            FEATURE_FLAGS.CUSTOMER_ANALYTICS,
            FEATURE_FLAGS.DATA_WAREHOUSE_SCENE,
            FEATURE_FLAGS.ENDPOINTS,
            FEATURE_FLAGS.LINKS,
            FEATURE_FLAGS.LIVE_DEBUGGER,
            FEATURE_FLAGS.WEB_ANALYTICS_MARKETING,
            FEATURE_FLAGS.PRODUCT_TOURS,
            FEATURE_FLAGS.USER_INTERVIEWS,
            FEATURE_FLAGS.WORKFLOWS,
        ],
    },
}

export default meta

const Template: StoryFn<StoryProps> = (props) => {
    const { setFeatureFlags: logicSetFeatureFlags } = useActions(featureFlagLogic)

    useEffect(() => {
        setFeatureFlags([FEATURE_FLAGS.CUSTOM_PRODUCTS_SIDEBAR])
        logicSetFeatureFlags([FEATURE_FLAGS.CUSTOM_PRODUCTS_SIDEBAR], {
            [FEATURE_FLAGS.CUSTOM_PRODUCTS_SIDEBAR]: 'test',
        })
    }, [logicSetFeatureFlags])

    return (
        <div className="w-[280px] h-[600px] border rounded bg-surface-primary overflow-hidden">
            <div className="p-2 border-b text-sm font-semibold text-secondary">Custom Products Sidebar</div>
            <div className="h-[calc(100%-40px)] overflow-auto group/colorful-product-icons colorful-product-icons-true">
                <ProjectTree root="custom-products://" onlyTree {...props} />
            </div>
        </div>
    )
}

export const Default: Story = Template.bind({})

// Story with narrow size (collapsed nav)
export const NarrowSize: Story = Template.bind({})
NarrowSize.args = {
    enableCustomProductsFlag: true,
    treeSize: 'narrow',
}

// Story showing the products sidebar (non-custom)
export const AllProducts: StoryFn<StoryProps> = () => {
    return (
        <div className="w-[280px] h-[600px] border rounded bg-surface-primary overflow-hidden">
            <div className="p-2 border-b text-sm font-semibold text-secondary">All Products Sidebar</div>
            <div className="h-[calc(100%-40px)] overflow-auto group/colorful-product-icons colorful-product-icons-true">
                <ProjectTree root="products://" onlyTree />
            </div>
        </div>
    )
}
