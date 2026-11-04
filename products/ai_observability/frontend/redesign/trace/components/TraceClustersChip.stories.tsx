import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_CLUSTER, FIXTURE_CLUSTERS_CHIP, FIXTURE_OUTLIER_CLUSTER, withWidth } from '../storyFixtures'
import { TraceClustersChip } from './TraceClustersChip'

const meta: Meta<typeof TraceClustersChip> = {
    title: 'Scenes-App/AI observability/Trace view/Trace clusters chip',
    component: TraceClustersChip,
    args: { first: FIXTURE_CLUSTER, others: [] },
}
export default meta

type Story = StoryObj<typeof TraceClustersChip>

export const OneCluster: Story = {}
export const OutlierOnly: Story = { args: { first: FIXTURE_OUTLIER_CLUSTER } }
export const LongTitleNarrow: Story = {
    args: {
        ...FIXTURE_CLUSTERS_CHIP,
        first: {
            ...FIXTURE_CLUSTER,
            label: 'Users who ask to restore an archived project after the retention window has passed',
        },
    },
    decorators: [withWidth(240)],
}
