import type { Meta, StoryObj } from '@storybook/react'

import type { TicketBriefApi } from '../../generated/api.schemas'
import { TicketBriefPanel } from './TicketBriefPanel'

const meta: Meta<typeof TicketBriefPanel> = {
    title: 'Scenes-App/Support/TicketBriefPanel',
    component: TicketBriefPanel,
    parameters: { layout: 'padded', viewMode: 'story' },
}
export default meta

type Story = StoryObj<typeof TicketBriefPanel>

const fullBrief: TicketBriefApi = {
    ask: 'Explain why the `checkout-redesign` flag returns false for every user, though it is rolled out to 100%.',
    area: 'Feature flags',
    questions: [
        'Why does the flag return false at 100% rollout?',
        'Does the release condition order matter?',
        'Is there a cache we can clear?',
    ],
    affected_items: [
        {
            kind: 'feature_flag',
            url: 'https://us.posthog.com/project/1/feature_flags/123',
            label: 'checkout-redesign',
        },
        {
            kind: 'insight',
            url: 'https://us.posthog.com/project/1/insights/abc123',
            label: 'Checkout conversion',
        },
    ],
    replay_url: 'https://us.posthog.com/project/1/replay/00000000-0000-4000-8000-000000000000',
    screenshot_urls: ['https://example.com/uploaded_media/flag-panel.png'],
    facts: ['Web SDK `1.240.0`', 'EU Cloud', 'Error: `Kind not configured`'],
    tried: ['Reset the rollout to 100%', 'Cleared local storage'],
}

const minimalBrief: TicketBriefApi = {
    ask: 'Raise the event ingestion limit for the month, because an import is being dropped.',
    area: 'Billing',
    questions: [],
}

export const FullBrief: Story = { args: { brief: fullBrief } }

export const AskOnly: Story = { args: { brief: minimalBrief } }
