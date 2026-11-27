import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../trace/storyFixtures'
import { VolumeCell } from './VolumeCell'

const meta: Meta<typeof VolumeCell> = {
    title: 'Scenes-App/AI observability/Diagnostics/Volume cell',
    component: VolumeCell,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { value: 410, max: 1240 },
    decorators: [withWidth(360)],
}
export default meta

type Story = StoryObj<typeof VolumeCell>

export const PartOfThePage: Story = {}
