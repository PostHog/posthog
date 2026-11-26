import type { Meta, StoryObj } from '@storybook/react'

import { OpenSessionPlaceholder } from './OpenSessionPlaceholder'

const meta: Meta<typeof OpenSessionPlaceholder> = {
    title: 'Scenes-App/AI observability/Sessions/Open session placeholder',
    component: OpenSessionPlaceholder,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { status: 'none', onRetry: () => {}, onClose: () => {} },
    decorators: [
        (StoryComponent) => (
            <div className="w-80 rounded border">
                <StoryComponent />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof OpenSessionPlaceholder>

export const NoneOpen: Story = {}

export const NotFound: Story = { args: { status: 'not_found' } }

export const Failed: Story = { args: { status: 'failed' } }
