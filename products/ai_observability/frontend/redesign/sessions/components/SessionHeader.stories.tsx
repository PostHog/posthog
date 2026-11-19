import type { Meta, StoryObj } from '@storybook/react'

import { makeTracePersonItem, makeTracePreview, ready } from '../../traces/testFixtures'
import { makeSessionListItem } from '../testFixtures'
import { SessionHeader } from './SessionHeader'

const item = makeSessionListItem()

const meta: Meta<typeof SessionHeader> = {
    title: 'Scenes-App/AI observability/Sessions/Session header',
    component: SessionHeader,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        item,
        title: ready(makeTracePreview(item.firstTraceId)),
        person: ready(makeTracePersonItem(item.firstTraceId).person),
        conversationOnly: false,
        onConversationOnlyChange: () => {},
    },
    decorators: [
        (StoryComponent) => (
            <div className="w-120 rounded border">
                <StoryComponent />
            </div>
        ),
    ],
}
export default meta

type Story = StoryObj<typeof SessionHeader>

export const Ready: Story = {}

export const ConversationOnly: Story = { args: { conversationOnly: true } }

export const Loading: Story = {
    args: { title: { status: 'loading' }, person: { status: 'loading' } },
    parameters: { testOptions: { snapshotBrowsers: [], waitForLoadersToDisappear: false } },
}

export const Untitled: Story = {
    args: { title: ready(makeTracePreview(item.firstTraceId, { input: null })), person: ready(null) },
}
