import type { Meta, StoryObj } from '@storybook/react'
import type { ReactElement } from 'react'
import { useState } from 'react'

import {
    Accordion,
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
    Badge,
    Card,
    DataTable,
    type DataTableColumn,
    DescriptionList,
    EmptyState,
    type EmptyStateIllustrationType,
    Link,
    ProgressBar,
    Select,
    Stack,
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
    Tooltip,
} from '../src/index'
import { McpThemeDecorator } from './decorator'

const meta: Meta = {
    title: 'Mosaic/Components',
    decorators: [McpThemeDecorator],
    parameters: {
        testOptions: {
            // Mosaic doesn't have dark mode built-in by default as it's fully controlled by the CSS variables set by the wrappers.
            skipDarkMode: true,
        },
    },
}
export default meta

type Story = StoryObj<{}>

// ---------------------------------------------------------------------------
// Section helper
// ---------------------------------------------------------------------------
function Section({ title, children }: { title: string; children: React.ReactNode }): ReactElement {
    return (
        <Stack gap="sm">
            <span style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--color-text-primary)' }}>{title}</span>
            {children}
        </Stack>
    )
}

// ===========================
// Base components
// ===========================

export const BadgeStory: Story = {
    storyName: 'Badge',
    render: () => (
        <Stack gap="md">
            <Section title="Variants">
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                    <Badge variant="success">Success</Badge>
                    <Badge variant="danger">Danger</Badge>
                    <Badge variant="warning">Warning</Badge>
                    <Badge variant="info">Info</Badge>
                    <Badge variant="neutral">Neutral</Badge>
                </div>
            </Section>
            <Section title="Sizes">
                <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
                    <Badge variant="info" size="sm">
                        Small
                    </Badge>
                    <Badge variant="info" size="md">
                        Medium
                    </Badge>
                </div>
            </Section>
        </Stack>
    ),
}

export const CardStory: Story = {
    storyName: 'Card',
    render: () => (
        <Stack gap="md">
            {(['sm', 'md', 'lg'] as const).map((padding) => (
                <Card key={padding} padding={padding}>
                    <span style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)' }}>
                        Card with <code>{padding}</code> padding
                    </span>
                </Card>
            ))}
        </Stack>
    ),
}

export const StackStory: Story = {
    storyName: 'Stack',
    render: () => {
        const box: React.CSSProperties = {
            padding: '0.5rem 0.75rem',
            borderRadius: '0.375rem',
            background: 'var(--color-background-info)',
            color: 'var(--color-text-info)',
            fontSize: '0.75rem',
            fontWeight: 500,
        }
        return (
            <Stack gap="md">
                <Section title="Column (default)">
                    <Stack gap="sm">
                        <div style={box}>Item 1</div>
                        <div style={box}>Item 2</div>
                        <div style={box}>Item 3</div>
                    </Stack>
                </Section>
                <Section title="Row">
                    <Stack direction="row" gap="sm">
                        <div style={box}>Item 1</div>
                        <div style={box}>Item 2</div>
                        <div style={box}>Item 3</div>
                    </Stack>
                </Section>
                <Section title="Row, space-between">
                    <Stack direction="row" gap="sm" justify="between">
                        <div style={box}>Left</div>
                        <div style={box}>Right</div>
                    </Stack>
                </Section>
            </Stack>
        )
    },
}

export const LinkStory: Story = {
    storyName: 'Link',
    render: () => (
        <Stack gap="sm">
            <Link href="https://posthog.com" external>
                External link
            </Link>
            <Link href="#">Internal link</Link>
            <Link href="https://posthog.com/docs" external className="text-xs">
                Small external link
            </Link>
        </Stack>
    ),
}

export const TooltipStory: Story = {
    storyName: 'Tooltip',
    render: () => (
        <Stack gap="md">
            <div style={{ display: 'flex', gap: '2rem', flexWrap: 'wrap', padding: '1.5rem 0' }}>
                <Tooltip content="This appears above" position="top" forceVisible>
                    <span
                        style={{
                            fontSize: '0.875rem',
                            cursor: 'default',
                            borderBottom: '1px dashed var(--color-text-secondary)',
                        }}
                    >
                        Top tooltip
                    </span>
                </Tooltip>
                <Tooltip content="This appears below" position="bottom" forceVisible>
                    <span
                        style={{
                            fontSize: '0.875rem',
                            cursor: 'default',
                            borderBottom: '1px dashed var(--color-text-secondary)',
                        }}
                    >
                        Bottom tooltip
                    </span>
                </Tooltip>
                <Tooltip content="Tooltips work on any element" forceVisible>
                    <Badge variant="info">Hover me</Badge>
                </Tooltip>
            </div>
        </Stack>
    ),
}

export const SelectStory: Story = {
    storyName: 'Select',
    render: () => {
        const [value, setValue] = useState('table')
        return (
            <Stack gap="md">
                <Section title="Default">
                    <Select
                        value={value}
                        onChange={setValue}
                        options={[
                            { value: 'table', label: 'Table' },
                            { value: 'bar', label: 'Bar chart' },
                            { value: 'line', label: 'Line chart' },
                        ]}
                    />
                </Section>
                <Section title="Small">
                    <Select
                        value={value}
                        onChange={setValue}
                        size="sm"
                        options={[
                            { value: 'table', label: 'Table' },
                            { value: 'bar', label: 'Bar chart' },
                        ]}
                    />
                </Section>
            </Stack>
        )
    },
}

export const TabsStory: Story = {
    storyName: 'Tabs',
    render: () => (
        <Card padding="none">
            <Tabs defaultValue="overview">
                <TabsList className="px-3">
                    <TabsTrigger value="overview">Overview</TabsTrigger>
                    <TabsTrigger value="details">Details</TabsTrigger>
                    <TabsTrigger value="settings">Settings</TabsTrigger>
                </TabsList>
                <TabsContent value="overview" className="px-4 pb-4">
                    <span style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)' }}>Overview content</span>
                </TabsContent>
                <TabsContent value="details" className="px-4 pb-4">
                    <span style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)' }}>Details content</span>
                </TabsContent>
                <TabsContent value="settings" className="px-4 pb-4">
                    <span style={{ fontSize: '0.875rem', color: 'var(--color-text-secondary)' }}>Settings content</span>
                </TabsContent>
            </Tabs>
        </Card>
    ),
}

// -- DataTable --

interface SampleRow {
    name: string
    country: string
    events: number
    revenue: number | null
    active: boolean
}

const sampleData: SampleRow[] = [
    { name: 'Acme Corp', country: 'US', events: 14280, revenue: 52000, active: true },
    { name: 'Globex', country: 'UK', events: 8930, revenue: 31500, active: true },
    { name: 'Initech', country: 'US', events: 6210, revenue: null, active: false },
    { name: 'Umbrella', country: 'JP', events: 22450, revenue: 89000, active: true },
    { name: 'Hooli', country: 'US', events: 3100, revenue: 12500, active: true },
    { name: 'Pied Piper', country: 'US', events: 45670, revenue: 120000, active: true },
    { name: 'Stark Ind.', country: 'US', events: 18900, revenue: 75000, active: false },
    { name: 'Wayne Ent.', country: 'US', events: 29300, revenue: 95000, active: true },
]

const sampleColumns: DataTableColumn<SampleRow>[] = [
    { key: 'name', header: 'Company', sortable: true },
    { key: 'country', header: 'Country', sortable: true },
    { key: 'events', header: 'Events', align: 'right', sortable: true },
    { key: 'revenue', header: 'Revenue', align: 'right', sortable: true },
    {
        key: 'active',
        header: 'Status',
        render: (row) => (
            <Badge variant={row.active ? 'success' : 'neutral'} size="sm">
                {row.active ? 'Active' : 'Inactive'}
            </Badge>
        ),
    },
]

export const DataTableStory: Story = {
    storyName: 'DataTable',
    render: () => (
        <DataTable
            columns={sampleColumns}
            data={sampleData}
            pageSize={5}
            defaultSort={{ key: 'events', direction: 'desc' }}
        />
    ),
}

// -- DescriptionList --

export const DescriptionListStory: Story = {
    storyName: 'DescriptionList',
    render: () => (
        <Stack gap="md">
            <Section title="Single column">
                <Card padding="md">
                    <DescriptionList
                        items={[
                            { label: 'Name', value: 'My Feature Flag' },
                            { label: 'Status', value: <Badge variant="success">Active</Badge> },
                            { label: 'Created', value: 'Jan 15, 2025' },
                            { label: 'Description', value: 'Enables the new onboarding flow for enterprise users' },
                        ]}
                    />
                </Card>
            </Section>
            <Section title="Two columns">
                <Card padding="md">
                    <DescriptionList
                        columns={2}
                        items={[
                            { label: 'Started', value: 'Jan 1, 2025' },
                            { label: 'Ended', value: 'Feb 28, 2025' },
                            { label: 'Type', value: 'Product' },
                            { label: 'Flag key', value: 'new-onboarding' },
                        ]}
                    />
                </Card>
            </Section>
        </Stack>
    ),
}

// -- ProgressBar --

export const ProgressBarStory: Story = {
    storyName: 'ProgressBar',
    render: () => (
        <Stack gap="md">
            <Section title="Variants">
                <Stack gap="sm">
                    <ProgressBar value={75} variant="info" showLabel />
                    <ProgressBar value={90} variant="success" showLabel />
                    <ProgressBar value={45} variant="warning" showLabel />
                    <ProgressBar value={20} variant="danger" showLabel />
                </Stack>
            </Section>
            <Section title="Sizes">
                <Stack gap="sm">
                    <ProgressBar value={60} variant="info" size="sm" showLabel />
                    <ProgressBar value={60} variant="info" size="md" showLabel />
                </Stack>
            </Section>
        </Stack>
    ),
}

// -- EmptyState --

export const EmptyStateStory: Story = {
    storyName: 'EmptyState',
    render: () => (
        <Stack gap="md">
            <Section title="Text only">
                <Card padding="md">
                    <EmptyState title="No data found" description="Try adjusting your filters or date range" />
                </Card>
            </Section>
            <Section title="With illustrations">
                <Stack gap="sm">
                    {(['table', 'chart', 'funnel', 'number', 'generic'] as EmptyStateIllustrationType[]).map((type) => (
                        <Card key={type} padding="md">
                            <EmptyState icon={type} description={`Empty state: ${type}`} />
                        </Card>
                    ))}
                </Stack>
            </Section>
            <Section title="Illustration with title and description">
                <Card padding="md">
                    <EmptyState
                        icon="table"
                        title="No rows to display"
                        description="Try adjusting your filters or date range"
                    />
                </Card>
            </Section>
        </Stack>
    ),
}

// -- Accordion --

export const AccordionStory: Story = {
    storyName: 'Accordion',
    render: () => (
        <Stack gap="md">
            <Section title="Single expand (default)">
                <Card padding="md">
                    <Accordion defaultExpanded={['item-1']}>
                        <AccordionItem value="item-1">
                            <AccordionTrigger>What is PostHog?</AccordionTrigger>
                            <AccordionContent>
                                <span className="text-sm text-text-secondary pl-5">
                                    PostHog is an open-source product analytics platform.
                                </span>
                            </AccordionContent>
                        </AccordionItem>
                        <AccordionItem value="item-2">
                            <AccordionTrigger>How do feature flags work?</AccordionTrigger>
                            <AccordionContent>
                                <span className="text-sm text-text-secondary pl-5">
                                    Feature flags let you toggle features for specific users or groups.
                                </span>
                            </AccordionContent>
                        </AccordionItem>
                        <AccordionItem value="item-3">
                            <AccordionTrigger>Can I self-host?</AccordionTrigger>
                            <AccordionContent>
                                <span className="text-sm text-text-secondary pl-5">
                                    Yes, PostHog can be self-hosted using Docker or Kubernetes.
                                </span>
                            </AccordionContent>
                        </AccordionItem>
                    </Accordion>
                </Card>
            </Section>
            <Section title="Multiple expand">
                <Card padding="md">
                    <Accordion multiple defaultExpanded={['m-1', 'm-2']}>
                        <AccordionItem value="m-1">
                            <AccordionTrigger>First section</AccordionTrigger>
                            <AccordionContent>
                                <span className="text-sm text-text-secondary pl-5">Content for the first section.</span>
                            </AccordionContent>
                        </AccordionItem>
                        <AccordionItem value="m-2">
                            <AccordionTrigger>Second section</AccordionTrigger>
                            <AccordionContent>
                                <span className="text-sm text-text-secondary pl-5">
                                    Content for the second section.
                                </span>
                            </AccordionContent>
                        </AccordionItem>
                        <AccordionItem value="m-3">
                            <AccordionTrigger>Third section</AccordionTrigger>
                            <AccordionContent>
                                <span className="text-sm text-text-secondary pl-5">Content for the third section.</span>
                            </AccordionContent>
                        </AccordionItem>
                    </Accordion>
                </Card>
            </Section>
        </Stack>
    ),
}
