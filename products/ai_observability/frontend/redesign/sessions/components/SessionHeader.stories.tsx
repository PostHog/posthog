import type { Meta, StoryObj } from '@storybook/react'

import { ready } from '../../traces/testFixtures'
import { makeSessionListItem, makeSessionPersonItem, makeSessionPreview } from '../testFixtures'
import { SessionHeader } from './SessionHeader'

const item = makeSessionListItem()

const meta: Meta<typeof SessionHeader> = {
    title: 'Scenes-App/AI observability/Sessions/Session header',
    component: SessionHeader,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        sessionId: item.id,
        item,
        title: ready(makeSessionPreview(item.id)),
        person: ready(makeSessionPersonItem(item.id).person),
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

const listNavigation = { fullPageHref: '/', listed: true, onPrevious: () => {}, onNext: null }

export const OpenedFromList: Story = { args: { listNavigation } }

export const OpenedFromListNarrow: Story = {
    args: { listNavigation, sessionId: 'sess_019113b0-7c3e-7f2a-9d41-long-custom-suffix' },
    decorators: [
        (StoryComponent) => (
            <div className="w-50">
                <StoryComponent />
            </div>
        ),
    ],
}

export const Loading: Story = {
    args: { item: null, title: { status: 'loading' }, person: { status: 'loading' } },
    parameters: { testOptions: { snapshotBrowsers: [], waitForLoadersToDisappear: false } },
}

export const Untitled: Story = {
    args: { title: ready(makeSessionPreview(item.id, { input: null })), person: ready(null) },
}

export const DetailsFailed: Story = {
    args: { title: { status: 'error' }, person: { status: 'error' }, onRetryDetails: () => {} },
}
