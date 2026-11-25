import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../trace/storyFixtures'
import { PersonDrawerToolbar } from './PersonDrawerToolbar'

const meta: Meta<typeof PersonDrawerToolbar> = {
    title: 'Scenes-App/AI observability/People/Person drawer toolbar',
    component: PersonDrawerToolbar,
    decorators: [withWidth(360)],
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { onClose: () => {} },
}
export default meta

type Story = StoryObj<typeof PersonDrawerToolbar>

export const Narrow: Story = {}
