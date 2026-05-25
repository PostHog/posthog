import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'

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
        featureFlags: {
            [FEATURE_FLAGS.CUSTOM_PRODUCTS_SIDEBAR]: 'test',
            [FEATURE_FLAGS.CUSTOMER_ANALYTICS]: true,
            [FEATURE_FLAGS.DATA_WAREHOUSE_SCENE]: true,
            [FEATURE_FLAGS.ENDPOINTS]: true,
            [FEATURE_FLAGS.LINKS]: true,
            [FEATURE_FLAGS.LIVE_DEBUGGER]: true,
            [FEATURE_FLAGS.WEB_ANALYTICS_MARKETING]: true,
            [FEATURE_FLAGS.PRODUCT_TOURS]: true,
            [FEATURE_FLAGS.USER_INTERVIEWS]: true,
        },
    },
    render: (props: StoryProps) => (
        <div className="w-[280px] h-[600px] border rounded bg-surface-primary overflow-hidden">
            <div className="p-2 border-b text-sm font-semibold text-secondary">Custom Products Sidebar</div>
            <div className="h-[calc(100%-40px)] overflow-auto group/colorful-product-icons colorful-product-icons-true">
                <ProjectTree root="custom-products://" onlyTree {...props} />
            </div>
        </div>
    ),
}

export default meta

export const Default: Story = {
    args: {},
}

// Story with narrow size (collapsed nav)
export const NarrowSize: Story = {
    args: {
        enableCustomProductsFlag: true,
        treeSize: 'narrow',
    },
}

// Story showing the products sidebar (non-custom)
export const AllProducts: Story = {
    render: () => {
        return (
            <div className="w-[280px] h-[600px] border rounded bg-surface-primary overflow-hidden">
                <div className="p-2 border-b text-sm font-semibold text-secondary">All Products Sidebar</div>
                <div className="h-[calc(100%-40px)] overflow-auto group/colorful-product-icons colorful-product-icons-true">
                    <ProjectTree root="products://" onlyTree />
                </div>
            </div>
        )
    },
}
