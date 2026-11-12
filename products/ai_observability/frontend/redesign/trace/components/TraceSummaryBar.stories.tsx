import type { Meta, StoryObj } from '@storybook/react'

import { FIXTURE_CLUSTERS, FIXTURE_SUMMARY_TRACE, withWidth } from '../storyFixtures'
import { TraceSummaryBar } from './TraceSummaryBar'

const meta: Meta<typeof TraceSummaryBar> = {
    title: 'Scenes-App/AI observability/Trace view/Trace summary bar',
    component: TraceSummaryBar,
    args: {
        trace: FIXTURE_SUMMARY_TRACE,
        clusters: null,
    },
}
export default meta

type Story = StoryObj<typeof TraceSummaryBar>

// The stats sit at the right end of the bar's width, so the stories pin one.
const wide: Story = { decorators: [withWidth(960)] }

export const Default: Story = wide
export const Anonymous: Story = { ...wide, args: { trace: { ...FIXTURE_SUMMARY_TRACE, person: null } } }
export const ShortId: Story = { ...wide, args: { trace: { ...FIXTURE_SUMMARY_TRACE, id: 'notes-run-42' } } }
export const LongSlugId: Story = {
    ...wide,
    args: { trace: { ...FIXTURE_SUMMARY_TRACE, id: 'support-chat-session-2026-09-01-weekly-billing-review' } },
}
export const WithClusters: Story = { ...wide, args: { clusters: FIXTURE_CLUSTERS } }
export const Narrow: Story = { args: { clusters: FIXTURE_CLUSTERS }, decorators: [withWidth(420)] }
export const WithFeedback: Story = {
    args: { feedback: { summary: { total: 6, thumbsUp: 0, thumbsDown: 0 }, onClick: () => {} } },
    decorators: [withWidth(420)],
}
export const WithThumbsFeedback: Story = {
    args: { feedback: { summary: { total: 6, thumbsUp: 3, thumbsDown: 1 }, onClick: () => {} } },
    decorators: [withWidth(420)],
}

export const WithGitBranch: Story = {
    ...wide,
    args: { git: { branch: 'feat/billing-answers', repo: 'acme/support-bot', pullRequest: null } },
}
export const NarrowWithLongGitBranch: Story = {
    decorators: [withWidth(420)],
    args: {
        git: {
            branch: 'carol/feat-answer-billing-questions-with-invoice-history-and-seat-changes',
            repo: null,
            pullRequest: null,
        },
    },
}
export const WithGitPullRequest: Story = {
    ...wide,
    args: {
        git: {
            branch: 'feat/billing-answers',
            repo: 'acme/support-bot',
            pullRequest: { repoOwner: 'acme', repoName: 'support-bot', number: 42, title: 'Answer billing questions' },
        },
    },
}

export const EveryChip: Story = {
    ...wide,
    args: {
        trace: {
            ...FIXTURE_SUMMARY_TRACE,
            id: 'support-chat-session-2026-09-01-weekly-billing-review',
            person: { distinctId: 'a', label: 'alexandra.konstantinopoulou@enterprise-customer.example.com' },
        },
        clusters: FIXTURE_CLUSTERS,
        evals: { summary: { passed: 2, failed: 3, unrated: 1, nodes: [] }, onClick: () => {} },
        feedback: { summary: { total: 6, thumbsUp: 3, thumbsDown: 1 }, onClick: () => {} },
        review: {
            status: { review: null, queue: { id: 'q1', name: 'Refund and billing escalations', itemId: 'i1' } },
            queueHref: '/reviews',
            onRemoveFromQueue: () => {},
        },
        git: { branch: 'feat/billing-answers', repo: 'acme/support-bot', pullRequest: null },
    },
}
