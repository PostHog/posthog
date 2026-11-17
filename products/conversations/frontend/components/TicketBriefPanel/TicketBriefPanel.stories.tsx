import type { Meta, StoryObj } from '@storybook/react'

import type { TicketBriefApi } from '../../generated/api.schemas'
import { TicketBriefPanel } from './TicketBriefPanel'

const meta: Meta<typeof TicketBriefPanel> = {
    title: 'Scenes-App/Support/TicketBriefPanel',
    component: TicketBriefPanel,
    parameters: { layout: 'padded', viewMode: 'story', testOptions: { snapshotBrowsers: [] } },
}
export default meta

type Story = StoryObj<typeof TicketBriefPanel>

const afterPostHogAiBrief: TicketBriefApi = {
    ask: 'Explain why the `checkout-redesign` flag returns false for every user, though it is rolled out to 100%.',
    purpose: 'Launch the new checkout to all customers before the end-of-month freeze.',
    area: 'Feature flags',
    questions: ['why does it say false when its at 100%??', 'does the order of the release conditions matter'],
    already_answered: 'PostHog AI said the flag is enabled and that local evaluation may cache the old value.',
    tried: ['Set the rollout back to 100%', 'Cleared local storage and reloaded the page'],
    where_stopped: 'It could not see which value the server returned for an identified user.',
    support_reason: 'The flag evaluation logs for the project are only visible to PostHog staff.',
    facts: ['Web SDK `1.240.0`', 'EU Cloud'],
    affected_items: [
        {
            kind: 'feature_flag',
            url: 'https://us.posthog.com/project/1/feature_flags/123',
            label: '123',
        },
        {
            kind: 'ai_conversation',
            url: 'https://us.posthog.com/project/1/tasks/t-42',
            label: 't-42',
        },
    ],
    replay_url: 'https://us.posthog.com/project/1/replay/00000000-0000-4000-8000-000000000000',
    screenshot_urls: ['https://example.com/uploaded_media/flag-panel.png'],
    error_message:
        'Traceback (most recent call last):\n  File "app/flags.py", line 212, in evaluate\n    return self._match(condition, properties)\n  File "app/flags.py", line 88, in _match\n    raise ConditionError("unknown operator: is_not_set_v2")\nConditionError: unknown operator: is_not_set_v2',
}

// The common shape: the customer said what they want, not why, and reported no error.
const minimalBrief: TicketBriefApi = {
    ask: 'Raise the event ingestion limit for the month, because an import is being dropped.',
    area: 'Billing',
    questions: [],
}

export const AfterPostHogAi: Story = { args: { brief: afterPostHogAiBrief } }

export const AskOnly: Story = { args: { brief: minimalBrief } }
