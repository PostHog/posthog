import type { Meta, StoryObj } from '@storybook/react'

import type { SignalReportApi } from 'products/signals/frontend/generated/api.schemas'

import { ThreadReportEntry } from './ThreadReports'

// The thread entry a support teammate reads on a ticket to see which reports came out of it.
// A ticket's fix is the headline, so the PR states get their own stories.

const meta: Meta<typeof ThreadReportEntry> = {
    title: 'Scenes-App/Support/ThreadReportEntry',
    component: ThreadReportEntry,
    parameters: { layout: 'padded', viewMode: 'story', mockDate: '2026-07-25' },
}
export default meta

type Story = StoryObj<typeof ThreadReportEntry>

function makeReport(overrides: Partial<SignalReportApi>): SignalReportApi {
    return {
        id: '019f9582-93e7-77c1-8912-4f541d70cb13',
        status: 'ready',
        title: 'perf(agent): cut latency on formatting-only edits',
        summary:
            'Formatting-only edits re-run full query generation, so a one-line change costs the same as a new question.\n\n## Problem\n\nThe agent rebuilds its whole plan per turn, and a formatting edit takes the same path as a fresh query.',
        implementation_pr_url: 'https://github.com/PostHog/posthog/pull/73646',
        implementation_pr_merged: false,
        ...overrides,
    } as SignalReportApi
}

function Thread({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="max-w-2xl">{children}</div>
}

export const FixProposed: Story = {
    render: () => (
        <Thread>
            <ThreadReportEntry report={makeReport({})} />
        </Thread>
    ),
}

export const FixMerged: Story = {
    render: () => (
        <Thread>
            <ThreadReportEntry report={makeReport({ implementation_pr_merged: true })} />
        </Thread>
    ),
}

export const SeveralReportsAcrossStates: Story = {
    render: () => (
        <Thread>
            <ThreadReportEntry report={makeReport({})} />
            <ThreadReportEntry
                report={makeReport({
                    id: '019f954a-8ed0-7a18-a198-3ffed1a2def0',
                    status: 'in_progress',
                    title: 'fix(agent): stop dropping chat history mid-run',
                    summary: 'The session is re-keyed when a tool call times out, so the thread restarts empty.',
                    implementation_pr_url: null,
                })}
            />
            <ThreadReportEntry
                report={makeReport({
                    id: '019f9569-5d45-780a-8b63-ecd0dc71148e',
                    status: 'pending_input',
                    title: null,
                    summary: 'Needs a product call on whether this should be rate-limited per project.',
                    implementation_pr_url: null,
                })}
            />
        </Thread>
    ),
}
