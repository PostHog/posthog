import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useEffect } from 'react'

import { useActions } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { mswDecorator, setFeatureFlags } from '~/mocks/browser'
import { UserProductListReason } from '~/queries/schema/schema-general'

import { ProjectTree, ProjectTreeProps } from './ProjectTree'

// Mock custom products with various reasons to show the different indicators
const MOCK_CUSTOM_PRODUCTS = [
    {
        id: 'product-1',
        product_path: 'Product analytics',
        enabled: true,
        reason: UserProductListReason.USED_BY_COLLEAGUES,
        reason_text: null,
        created_at: new Date().toISOString(), // Recent, should show green dot
        updated_at: new Date().toISOString(),
    },
    {
        id: 'product-2',
        product_path: 'Session replay',
        enabled: true,
        reason: UserProductListReason.NEW_PRODUCT,
        reason_text: 'This is a brand new product we just launched!',
        created_at: new Date().toISOString(), // Recent, should show green dot
        updated_at: new Date().toISOString(),
    },
    {
        id: 'product-3',
        product_path: 'Feature flags',
        enabled: true,
        reason: UserProductListReason.USED_ON_SEPARATE_TEAM, // Should NOT show green dot
        reason_text: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    },
    {
        id: 'product-4',
        product_path: 'Dashboards',
        enabled: true,
        reason: UserProductListReason.SALES_LED,
        reason_text: null,
        created_at: new Date(Date.now() - 10 * 24 * 60 * 60 * 1000).toISOString(), // 10 days ago, should NOT show dot
        updated_at: new Date().toISOString(),
    },
    {
        id: 'product-5',
        product_path: 'Experiments',
        enabled: true,
        reason: UserProductListReason.USED_SIMILAR_PRODUCTS,
        reason_text: null,
        created_at: new Date().toISOString(), // Recent, should show green dot
        updated_at: new Date().toISOString(),
    },
]

interface StoryProps extends ProjectTreeProps {
    enableCustomProductsFlag?: boolean
}

type Story = StoryObj<(props: StoryProps) => JSX.Element>

const meta: Meta<(props: StoryProps) => JSX.Element> = {
    title: 'Layout/Project Tree/Custom Products',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
    },
    decorators: [
        mswDecorator({
            get: {
                '/api/environments/:team_id/user_product_list/': {
                    count: MOCK_CUSTOM_PRODUCTS.length,
                    results: MOCK_CUSTOM_PRODUCTS,
                    next: null,
                    previous: null,
                },
                '/api/environments/:team_id/file_system/': {
                    count: 0,
                    results: [],
                    next: null,
                    previous: null,
                },
                '/api/environments/:team_id/file_system_shortcut/': {
                    count: 0,
                    results: [],
                    next: null,
                    previous: null,
                },
            },
        }),
    ],
}

export default meta

const Template: StoryFn<StoryProps> = ({ enableCustomProductsFlag = true, ...props }) => {
    const { setFeatureFlags: setFlags } = useActions(featureFlagLogic)

    useEffect(() => {
        // Enable the custom products sidebar feature flag
        if (enableCustomProductsFlag) {
            setFeatureFlags([FEATURE_FLAGS.CUSTOM_PRODUCTS_SIDEBAR])
            setFlags([FEATURE_FLAGS.CUSTOM_PRODUCTS_SIDEBAR], {
                [FEATURE_FLAGS.CUSTOM_PRODUCTS_SIDEBAR]: 'test',
            })
        }
    }, [enableCustomProductsFlag, setFlags])

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
Default.args = {
    enableCustomProductsFlag: true,
}
Default.parameters = {
    docs: {
        description: {
            story: `Shows the custom products sidebar with green indicators for recently added products.
            
- **Product analytics** and **Session replay** have green dots (added by colleagues / new product)
- **Feature flags** does NOT have a green dot (USED_ON_SEPARATE_TEAM is excluded)
- **Dashboards** does NOT have a green dot (added more than 7 days ago)
- **Experiments** has a green dot (uses similar products)

Hover over items with green dots to dismiss them (persisted in localStorage).`,
        },
    },
}

// Story with narrow size (collapsed nav)
export const NarrowSize: Story = Template.bind({})
NarrowSize.args = {
    enableCustomProductsFlag: true,
    treeSize: 'narrow',
}

// Story showing the products sidebar (non-custom)
const ProductsTemplate: StoryFn<StoryProps> = (props) => {
    return (
        <div className="w-[280px] h-[600px] border rounded bg-surface-primary overflow-hidden">
            <div className="p-2 border-b text-sm font-semibold text-secondary">All Products Sidebar</div>
            <div className="h-[calc(100%-40px)] overflow-auto group/colorful-product-icons colorful-product-icons-true">
                <ProjectTree root="products://" onlyTree {...props} />
            </div>
        </div>
    )
}

export const AllProducts: Story = ProductsTemplate.bind({})
AllProducts.args = {}
AllProducts.parameters = {
    docs: {
        description: {
            story: 'Shows the default all products sidebar (without custom products feature flag).',
        },
    },
}

// Story showing shortcuts
const ShortcutsTemplate: StoryFn<StoryProps> = (props) => {
    return (
        <div className="w-[280px] h-[600px] border rounded bg-surface-primary overflow-hidden">
            <div className="p-2 border-b text-sm font-semibold text-secondary">Shortcuts Sidebar</div>
            <div className="h-[calc(100%-40px)] overflow-auto group/colorful-product-icons colorful-product-icons-true">
                <ProjectTree root="shortcuts://" onlyTree {...props} />
            </div>
        </div>
    )
}

export const Shortcuts: Story = ShortcutsTemplate.bind({})
Shortcuts.args = {}
Shortcuts.parameters = {
    docs: {
        description: {
            story: 'Shows the shortcuts sidebar.',
        },
    },
}
