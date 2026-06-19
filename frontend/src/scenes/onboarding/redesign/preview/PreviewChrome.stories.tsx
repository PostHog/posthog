import { Meta, StoryObj } from '@storybook/react'

import { ProductKey } from '~/queries/schema/schema-general'

import { buildPreviewConfig } from './presets'
import { PreviewChrome } from './PreviewChrome'
import { type MetricCard } from './types'

const DEMO_PRODUCTS = [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY, ProductKey.FEATURE_FLAGS]
const DEMO_METRICS: MetricCard[] = [
    { label: 'Unique visitors', value: '48,291', delta: '12.4%', deltaPositive: true },
    { label: 'Pageviews', value: '193k', delta: '8.1%', deltaPositive: true },
    { label: 'Conversion', value: '3.2%', delta: '0.4%', deltaPositive: true },
]

const meta: Meta<typeof PreviewChrome> = {
    title: 'Scenes-Other/Onboarding/Redesign Preview',
    component: PreviewChrome,
    parameters: { layout: 'centered' },
    // The preview fills its container, so the story frames it at a representative size.
    decorators: [
        (Story) => (
            <div className="h-[460px] w-[640px]">
                <Story />
            </div>
        ),
    ],
    // The `config` object is editable from the Controls panel — switch page kind, products, org name live.
}
export default meta

type Story = StoryObj<typeof PreviewChrome>

export const Dashboard: Story = {
    args: {
        config: {
            org: { name: 'Acme' },
            sidebar: { products: DEMO_PRODUCTS },
            page: { kind: 'dashboard', metrics: DEMO_METRICS, showTrend: true, showBars: true },
        },
    },
}

export const Empty: Story = {
    args: {
        config: {
            org: { name: 'Acme' },
            sidebar: { products: [] },
            page: {
                kind: 'empty',
                title: 'Your workspace is taking shape',
                subtitle: 'Name your organization to begin.',
            },
        },
    },
}

export const CreateOrgStepPreset: Story = {
    args: { config: buildPreviewConfig('create_org', { orgName: 'Acme', products: DEMO_PRODUCTS }) },
}

export const CompanyStepPreset: Story = {
    args: { config: buildPreviewConfig('company', { orgName: 'Acme', products: DEMO_PRODUCTS }) },
}
