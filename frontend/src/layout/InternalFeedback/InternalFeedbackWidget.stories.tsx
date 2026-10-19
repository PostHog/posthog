import { Meta, StoryObj } from '@storybook/react'

import { LemonButton, LemonDropdown } from '@posthog/lemon-ui'

import { InternalFeedbackWidget } from './InternalFeedbackWidget'

const meta: Meta<typeof InternalFeedbackWidget> = {
    title: 'Layout/Internal Feedback Widget',
    component: InternalFeedbackWidget,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
    },
}
export default meta
type Story = StoryObj<typeof InternalFeedbackWidget>

export const WithOpenMenu: Story = {
    render: () => (
        <div className="h-screen flex flex-col gap-4 p-4 bg-primary">
            <div className="h-64 overflow-y-auto border rounded p-2 space-y-2" data-attr="story-scroll-area">
                {Array.from({ length: 30 }, (_, i) => (
                    <LemonButton key={i} type="secondary" data-attr={`story-row-${i}`}>
                        Row {i + 1}
                    </LemonButton>
                ))}
            </div>
            <LemonDropdown
                visible
                overlay={
                    <div className="p-2 space-y-1">
                        <LemonButton fullWidth data-attr="story-menu-item">
                            Menu item in a portal
                        </LemonButton>
                    </div>
                }
            >
                <LemonButton type="primary" className="self-start">
                    Open menu
                </LemonButton>
            </LemonDropdown>
            <InternalFeedbackWidget />
        </div>
    ),
}
