import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import {
    makeReport,
    mockArtefacts,
    mockReportTasks,
    mockReviewers,
    mockSignals,
    mockTask,
    pullRequestReports,
    reportTabReports,
    runReportsMany,
} from '../../__mocks__/inboxMocks'
import { SignalReportStatus } from '../../types'
import { AgentRunDetail } from './AgentRunDetail'
import { PullRequestDetail } from './PullRequestDetail'
import { ReportDetail } from './ReportDetail'

// Detail-body stories. Each detail component mounts the keyed `inboxReportDetailLogic`,
// which fetches artefacts / signals / tasks — mocked here. Polish the two-column detail
// layout (summary, evidence, runs, reviewers) against the desktop detail views.

const detailMocks = mswDecorator({
    get: {
        '/api/projects/:id/signals/reports/:reportId/artefacts': (req) => [
            200,
            mockArtefacts(req.params.reportId as string),
        ],
        '/api/projects/:id/signals/reports/:reportId/signals': (req) => [
            200,
            { report: null, signals: mockSignals(req.params.reportId as string, 4) },
        ],
        '/api/projects/:id/signals/reports/:reportId/tasks': (req) => [
            200,
            mockReportTasks(req.params.reportId as string),
        ],
        '/api/projects/:id/signals/reports/available_reviewers': () => [200, mockReviewers],
        '/api/projects/:id/tasks/:taskId': (req) => [200, mockTask(req.params.taskId as string)],
    },
})

const meta: Meta = {
    title: 'Scenes-App/Inbox/Detail',
    parameters: { layout: 'fullscreen', viewMode: 'story', mockDate: '2026-06-11' },
    decorators: [detailMocks],
}
export default meta

type Story = StoryObj

function Frame({ children }: { children: React.ReactNode }): JSX.Element {
    return <div className="bg-primary min-h-screen py-4">{children}</div>
}

export const Report: Story = {
    render: () => (
        <Frame>
            <ReportDetail report={reportTabReports[0]} />
        </Frame>
    ),
}

export const ReportMinimal: Story = {
    render: () => (
        <Frame>
            <ReportDetail
                report={makeReport({
                    title: 'No summary yet',
                    summary: null,
                    status: SignalReportStatus.CANDIDATE,
                    signal_count: 1,
                })}
            />
        </Frame>
    ),
}

export const PullRequest: Story = {
    render: () => (
        <Frame>
            <PullRequestDetail report={pullRequestReports[0]} />
        </Frame>
    ),
}

export const RunInProgress: Story = {
    render: () => (
        <Frame>
            <AgentRunDetail report={runReportsMany.find((r) => r.status === SignalReportStatus.IN_PROGRESS)!} />
        </Frame>
    ),
}

export const RunFailed: Story = {
    render: () => (
        <Frame>
            <AgentRunDetail report={runReportsMany.find((r) => r.status === SignalReportStatus.FAILED)!} />
        </Frame>
    ),
}

export const RunReady: Story = {
    render: () => (
        <Frame>
            <AgentRunDetail report={pullRequestReports[0]} />
        </Frame>
    ),
}
