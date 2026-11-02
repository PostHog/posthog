import { Meta, StoryObj } from '@storybook/react'

import { NodeKind } from '~/queries/schema/schema-general'

import { catalogMetricWorksheet } from './biCatalog'
import { BIMetricSnapshotContext } from './BIMetricSnapshotContext'

const config = catalogMetricWorksheet({
    id: 'example-revenue',
    name: 'revenue',
    status: 'approved',
    is_drifted: false,
    unit: 'usd',
    owner: 'analyst@example.com',
    definition: { kind: NodeKind.HogQLQuery, query: 'SELECT 42 AS revenue' },
})!.config

const meta: Meta<typeof BIMetricSnapshotContext> = {
    title: 'Products/Business intelligence/Metric snapshot context',
    component: BIMetricSnapshotContext,
    args: { config },
}
export default meta
type Story = StoryObj<typeof meta>
export const Approved: Story = {}
export const Proposed: Story = {
    args: { config: { ...config, catalogMetricContext: { ...config.catalogMetricContext!, status: 'proposed' } } },
}
export const Drifted: Story = {
    args: { config: { ...config, catalogMetricContext: { ...config.catalogMetricContext!, isDrifted: true } } },
}
export const Legacy: Story = { args: { config: { ...config, catalogMetricContext: undefined } } }
