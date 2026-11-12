import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_CLUSTER, FIXTURE_CLUSTERS, FIXTURE_OUTLIER_CLUSTER, withWidth } from '../storyFixtures'
import { TraceClustersChip } from './TraceClustersChip'

const meta: Meta<typeof TraceClustersChip> = {
    title: 'Scenes-App/AI observability/Trace view/Trace clusters chip',
    component: TraceClustersChip,
    args: { clusters: [FIXTURE_CLUSTER] },
}
export default meta

type Story = StoryObj<typeof TraceClustersChip>

export const OneCluster: Story = {}
export const OutlierOnly: Story = { args: { clusters: [FIXTURE_OUTLIER_CLUSTER] } }
export const LongTitleNarrow: Story = {
    args: {
        clusters: [
            {
                ...FIXTURE_CLUSTER,
                label: 'Users who ask to restore an archived project after the retention window has passed',
            },
            ...FIXTURE_CLUSTERS.slice(1),
        ],
    },
    decorators: [withWidth(240)],
}
