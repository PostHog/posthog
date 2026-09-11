import type { Meta, StoryObj } from '@storybook/react'

import { UrlRegexPreviewStatus } from './UrlRegexPreviewStatus'

const meta: Meta<typeof UrlRegexPreviewStatus> = {
    title: 'Components/IngestionControls/URL regex preview status',
    component: UrlRegexPreviewStatus,
    parameters: { testOptions: { snapshotTargetSelector: '#target' } },
    render: (args) => (
        <div id="target" className="w-200 max-w-full">
            <UrlRegexPreviewStatus {...args} />
        </div>
    ),
}
export default meta
type Story = StoryObj<typeof UrlRegexPreviewStatus>

export const Pending: Story = { args: { preview: { status: 'pending' } } }
export const TimedOut: Story = { args: { preview: { status: 'error', error: 'timeout' } } }
export const Unavailable: Story = { args: { preview: { status: 'error', error: 'unavailable' } } }
export const InvalidPattern: Story = { args: { preview: { status: 'success', results: [{ error: 'syntax_error' }] } } }
export const NoMatch: Story = { args: { preview: { status: 'success', results: [{ matches: false }] } } }
export const Narrow: Story = {
    args: Unavailable.args,
    render: (args) => (
        <div id="target" className="w-128 max-w-full">
            <UrlRegexPreviewStatus {...args} />
        </div>
    ),
}
