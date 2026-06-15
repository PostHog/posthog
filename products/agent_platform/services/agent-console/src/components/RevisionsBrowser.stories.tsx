import type { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { weeklyDigest, weeklyDigestRevisions } from '@posthog/agent-chat/fixtures'

import { RevisionsBrowser } from './RevisionsBrowser'

const meta: Meta<typeof RevisionsBrowser> = {
    title: 'Agent console components/RevisionsBrowser',
    component: RevisionsBrowser,
    parameters: { layout: 'fullscreen' },
    decorators: [
        (Story) => (
            <div className="p-6">
                <Story />
            </div>
        ),
    ],
}

export default meta
type Story = StoryObj<typeof RevisionsBrowser>

export const Default: Story = {
    render: () => {
        const [selectedId, setSelectedId] = useState<string | null>(weeklyDigest.live_revision)
        return (
            <RevisionsBrowser
                agent={weeklyDigest}
                revisions={weeklyDigestRevisions}
                selectedRevisionId={selectedId}
                onSelectRevision={setSelectedId}
            />
        )
    },
}

export const DraftSelected: Story = {
    render: () => {
        const draft = weeklyDigestRevisions.find((r) => r.state === 'draft')!
        const [selectedId, setSelectedId] = useState<string | null>(draft.id)
        return (
            <RevisionsBrowser
                agent={weeklyDigest}
                revisions={weeklyDigestRevisions}
                selectedRevisionId={selectedId}
                onSelectRevision={setSelectedId}
            />
        )
    },
}

export const NoLiveYet: Story = {
    render: () => {
        const draft = weeklyDigestRevisions.find((r) => r.state === 'draft')!
        const [selectedId, setSelectedId] = useState<string | null>(draft.id)
        return (
            <RevisionsBrowser
                agent={{ ...weeklyDigest, live_revision: null }}
                revisions={[draft]}
                selectedRevisionId={selectedId}
                onSelectRevision={setSelectedId}
            />
        )
    },
}

export const NoRevisions: Story = {
    render: () => (
        <RevisionsBrowser
            agent={{ ...weeklyDigest, live_revision: null }}
            revisions={[]}
            selectedRevisionId={null}
            onSelectRevision={() => undefined}
        />
    ),
}
