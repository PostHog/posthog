import { Meta, StoryObj } from '@storybook/react'

import { ProductKey } from '~/queries/schema/schema-general'

import { buildPreviewConfig } from './presets'
import { PreviewChrome } from './PreviewChrome'
import { type ChartBlock, type MetricCard, type SidebarSection } from './types'

const DEMO_PRODUCTS = [ProductKey.PRODUCT_ANALYTICS, ProductKey.SESSION_REPLAY, ProductKey.FEATURE_FLAGS]
const DEMO_METRICS: MetricCard[] = [
    { label: 'Unique visitors', value: '48,291', delta: '12.4%', deltaPositive: true },
    { label: 'Pageviews', value: '193k', delta: '8.1%', deltaPositive: true },
    { label: 'Conversion', value: '3.2%', delta: '0.4%', deltaPositive: true },
]
const DEMO_CHARTS: ChartBlock[] = [
    { title: 'Pageviews · trends', kind: 'trend' },
    { title: 'Top events', kind: 'bars' },
    {
        title: 'Top pages',
        kind: 'table',
        rows: [
            { label: '/home', value: '48,291' },
            { label: '/pricing', value: '32,104' },
            { label: '/docs', value: '18,227' },
            { label: '/blog', value: '12,840' },
        ],
    },
]

const DEFAULT_SECTIONS: SidebarSection[] = [
    {
        title: 'Project',
        items: [
            { label: 'Home', iconKey: 'home', active: true },
            { label: 'Inbox', iconKey: 'inbox' },
            { label: 'Activity', iconKey: 'activity' },
            { label: 'Data', iconKey: 'data', expandable: true },
            { label: 'Files', iconKey: 'files', expandable: true },
            { label: 'Apps', iconKey: 'apps', expandable: true },
            { label: 'Starred', iconKey: 'starred', expandable: true },
        ],
    },
]

const DEFAULT_FOOTER = [
    { label: 'Notifications', iconKey: 'notifications' },
    { label: 'Settings', iconKey: 'gear' },
    { label: 'Help', iconKey: 'help' },
]

const meta: Meta<typeof PreviewChrome> = {
    title: 'Scenes-Other/Onboarding/Redesign Preview',
    component: PreviewChrome,
    parameters: { layout: 'centered' },
    decorators: [
        (Story) => (
            <div className="h-[460px] w-[640px]">
                <Story />
            </div>
        ),
    ],
    argTypes: {
        config: { control: 'object' },
    },
}
export default meta

type Story = StoryObj<typeof PreviewChrome>

export const Dashboard: Story = {
    args: {
        config: {
            org: { name: 'Acme Corp' },
            sidebar: { sections: DEFAULT_SECTIONS, footerItems: DEFAULT_FOOTER },
            page: {
                kind: 'dashboard',
                metrics: DEMO_METRICS,
                charts: DEMO_CHARTS,
            },
        },
    },
    argTypes: {
        'config.org.name': { control: 'text', name: 'Org name' },
        'config.page.kind': { control: 'select', options: ['dashboard', 'empty', 'insight'], name: 'Page kind' },
        'config.page.metrics': { control: 'object', name: 'Metrics' },
        'config.page.charts': { control: 'object', name: 'Charts' },
        'config.sidebar.sections': { control: 'object', name: 'Sidebar sections' },
        'config.sidebar.footerItems': { control: 'object', name: 'Footer items' },
    },
}

export const Empty: Story = {
    args: {
        config: {
            org: { name: 'Acme Corp' },
            sidebar: {
                sections: [
                    {
                        title: 'Project',
                        items: [
                            { label: 'Home', iconKey: 'home', active: true },
                            { label: 'Activity', iconKey: 'activity' },
                            { label: 'Data', iconKey: 'data', expandable: true },
                            { label: 'Files', iconKey: 'files', expandable: true },
                        ],
                    },
                ],
                footerItems: DEFAULT_FOOTER,
            },
            page: {
                kind: 'empty',
                title: 'Your workspace is taking shape',
                subtitle: 'Name your organization to begin.',
            },
        },
    },
    argTypes: {
        'config.org.name': { control: 'text', name: 'Org name' },
        'config.page.kind': { control: 'select', options: ['dashboard', 'empty', 'insight'], name: 'Page kind' },
        'config.page.title': { control: 'text', name: 'Empty title' },
        'config.page.subtitle': { control: 'text', name: 'Empty subtitle' },
        'config.sidebar.sections': { control: 'object', name: 'Sidebar sections' },
        'config.sidebar.footerItems': { control: 'object', name: 'Footer items' },
    },
}

export const CreateOrgStepPreset: Story = {
    args: { config: buildPreviewConfig('create_org', { orgName: 'Acme Corp', products: [], userName: 'Fernando' }) },
    argTypes: {
        'config.org.name': { control: 'text', name: 'Org name' },
        'config.page.greetingName': { control: 'text', name: 'Greeting name' },
        'config.page.pinnedDashboards': { control: 'object', name: 'Pinned dashboards' },
        'config.page.recents': { control: 'object', name: 'Recents' },
        'config.page.starred': { control: 'object', name: 'Starred' },
        'config.sidebar.sections': { control: 'object', name: 'Sidebar sections' },
        'config.sidebar.footerItems': { control: 'object', name: 'Footer items' },
    },
}

export const CompanyStepPreset: Story = {
    args: { config: buildPreviewConfig('company', { orgName: 'Acme Corp', products: DEMO_PRODUCTS }) },
    argTypes: {
        'config.org.name': { control: 'text', name: 'Org name' },
        'config.page.kind': { control: 'select', options: ['dashboard', 'empty', 'insight'], name: 'Page kind' },
        'config.page.metrics': { control: 'object', name: 'Metrics' },
        'config.page.charts': { control: 'object', name: 'Charts' },
        'config.sidebar.sections': { control: 'object', name: 'Sidebar sections' },
        'config.sidebar.footerItems': { control: 'object', name: 'Footer items' },
    },
}
