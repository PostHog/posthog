import type { Meta, StoryObj } from '@storybook/react'

import { withWidth } from '../../trace/storyFixtures'
import { ErrorsSetupState } from './ErrorsSetupState'

const meta: Meta<typeof ErrorsSetupState> = {
    title: 'Scenes-App/AI observability/Errors/Errors setup state',
    component: ErrorsSetupState,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { tracesHref: '/ai-observability/traces', 'data-attr': 'errors-list' },
}
export default meta

type Story = StoryObj<typeof ErrorsSetupState>

export const FullWidth: Story = {}

export const NarrowContainer: Story = {
    decorators: [withWidth(360)],
}
