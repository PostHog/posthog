import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../trace/storyFixtures'
import { ToolsSetupState } from './ToolsSetupState'

const meta: Meta<typeof ToolsSetupState> = {
    title: 'Scenes-App/AI observability/Tools/Tools setup state',
    component: ToolsSetupState,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { tracesHref: '/ai-observability/traces', 'data-attr': 'tools-list' },
    decorators: [withWidth(360)],
}
export default meta

type Story = StoryObj<typeof ToolsSetupState>

export const NarrowContainer: Story = {}
