import type { Meta, StoryObj } from '@storybook/react'

import { makeReport, pullRequestReports, reportTabReports, runReportsMany } from '../../__mocks__/inboxMocks'
import { SignalReportStatus } from '../../types'
import { AgentRunCard } from './AgentRunCard'
import { CardSkeleton } from './CardSkeleton'
import { ReportCard } from './ReportCard'

// Individual card stories across every state, so card design / badges / right-rail
// density can be polished in isolation against the desktop equivalents.

const meta: Meta = {
    title: 'Scenes-App/Inbox/Cards',
    parameters: { layout: 'fullscreen', viewMode: 'story', mockDate: '2026-06-11' },
}
export default meta

type Story = StoryObj

function Stack({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="bg-primary min-h-screen mx-auto max-w-4xl px-6 py-6 flex flex-col gap-3">{children}</div>
}

export const ReportCards: Story = {
    render: () => (
        <Stack>
            {reportTabReports.map((r) => (
                <ReportCard key={r.id} report={r} />
            ))}
        </Stack>
    ),
}

export const PullRequestCards: Story = {
    render: () => (
        <Stack>
            {pullRequestReports.map((r) => (
                <ReportCard key={r.id} report={r} />
            ))}
        </Stack>
    ),
}

export const AgentRunCards: Story = {
    render: () => (
        <Stack>
            {runReportsMany.map((r) => (
                <AgentRunCard key={r.id} report={r} />
            ))}
        </Stack>
    ),
}

export const ReportCardStates: Story = {
    render: () => (
        <Stack>
            <ReportCard
                report={makeReport({
                    title: 'P0 critical, immediately actionable',
                    priority: 'P0',
                    actionability: 'immediately_actionable',
                    source_products: ['error_tracking'],
                    is_suggested_reviewer: true,
                    summary: 'Highest severity, clean fix available.',
                })}
            />
            <ReportCard
                report={makeReport({
                    title: 'Requires human input',
                    priority: 'P2',
                    actionability: 'requires_human_input',
                    source_products: ['session_replay', 'zendesk'],
                    summary: 'Needs a product call before an agent can proceed.',
                })}
            />
            <ReportCard
                report={makeReport({
                    title: 'No summary yet, still collecting context',
                    status: SignalReportStatus.CANDIDATE,
                    priority: null,
                    actionability: null,
                    summary: null,
                    source_products: ['llm_analytics'],
                })}
            />
            <ReportCard
                report={makeReport({
                    title: 'Not actionable, low priority',
                    priority: 'P4',
                    actionability: 'not_actionable',
                    source_products: ['github'],
                    summary: 'Real but insignificant.',
                })}
            />
        </Stack>
    ),
}

export const Skeleton: Story = {
    // Skeletons render permanently, so the VR runner must not wait for loaders to disappear.
    parameters: { testOptions: { waitForLoadersToDisappear: false } },
    render: () => (
        <Stack>
            {/* Dashed report/not-actionable card skeletons, then solid PR card skeletons – matching the live tabs. */}
            <CardSkeleton count={3} variant="cards" />
            <CardSkeleton count={2} variant="cards" dashed={false} />
        </Stack>
    ),
}
