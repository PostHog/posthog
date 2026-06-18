import type { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { delay, HttpResponse } from 'msw'
import { useEffect } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { setFeatureFlags, useStorybookMocks } from '~/mocks/browser'
import { toPaginatedResponse } from '~/mocks/handlers'

import { ProjectTree, ProjectTreeProps } from './ProjectTree'

// A mix of object types living at the root of the project file tree, used to show how the
// `type` prop force-filters the tree down to a single product's objects.
const MOCK_PROJECT_FILES = [
    { id: 'f-1', path: 'Marketing', type: 'folder' },
    { id: 'f-2', path: 'Product', type: 'folder' },
    { id: 'd-1', path: 'Revenue overview', type: 'dashboard', ref: '1', href: '/dashboard/1' },
    { id: 'd-2', path: 'Growth metrics', type: 'dashboard', ref: '2', href: '/dashboard/2' },
    { id: 'i-1', path: 'Weekly active users', type: 'insight/trends', ref: '3', href: '/insights/3' },
    { id: 'i-2', path: 'Signup funnel', type: 'insight/funnels', ref: '4', href: '/insights/4' },
    { id: 'ff-1', path: 'new-onboarding', type: 'feature_flag', ref: '5', href: '/feature_flags/5' },
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
        ],
    },
    render: (props: StoryProps) => {
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
    },
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

// Renders the project file tree with the given `type` filter, mocking the file system API.
const TypeFilteredTree = ({ label, type }: { label: string; type?: string }): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/environments/:team_id/file_system/': async () => {
                await delay(10)
                return HttpResponse.json(toPaginatedResponse(MOCK_PROJECT_FILES))
            },
        },
    })

    return (
        <div className="w-[280px] h-[600px] border rounded bg-surface-primary overflow-hidden">
            <div className="p-2 border-b text-sm font-semibold text-secondary">{label}</div>
            <div className="h-[calc(100%-40px)] overflow-auto group/colorful-product-icons colorful-product-icons-true">
                <ProjectTree root="project://" type={type} onlyTree logicKey={`type-filtered-${type ?? 'all'}`} />
            </div>
        </div>
    )
}

// Unfiltered project tree — every object type shows alongside folders.
export const ProjectTreeAllTypes: Story = {
    render: () => <TypeFilteredTree label="Project tree — all objects" />,
    parameters: {
        docs: { description: { story: 'The full project tree with no `type` filter: folders plus all objects.' } },
    },
}

// Force-filtered to dashboards only — leaf objects of other types are hidden, folders stay.
export const ProjectTreeDashboardsOnly: Story = {
    render: () => <TypeFilteredTree label="Project tree — dashboards only" type="dashboard" />,
    parameters: {
        docs: {
            description: {
                story: 'With `type="dashboard"`, only dashboard objects render. Folders are kept so the tree stays navigable.',
            },
        },
    },
}

// Force-filtered to insights only — matches the `insight/*` subtypes via type-prefix matching.
export const ProjectTreeInsightsOnly: Story = {
    render: () => <TypeFilteredTree label="Project tree — insights only" type="insight" />,
    parameters: {
        docs: {
            description: {
                story: 'With `type="insight"`, objects whose type is `insight` or any `insight/*` subtype render; other types are hidden.',
            },
        },
    },
}
