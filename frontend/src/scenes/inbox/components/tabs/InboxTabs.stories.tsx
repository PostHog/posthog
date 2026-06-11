import type { Meta, StoryObj } from '@storybook/react'

import { pullRequestReports, reportTabReports, runReportsFew, runReportsMany } from '../../__mocks__/inboxMocks'
import { PullRequestsTab } from './PullRequestsTab'
import { ReportsTab } from './ReportsTab'
import { RunsTab } from './RunsTab'

// Prop-driven stories for the three inbox tab bodies. No API — the central scene
// filters reports per tab and passes them in, so these render the full card list
// (or empty state) directly. Use these to polish list density, card design, and
// the Runs-tab queued / live / finished sections.

const meta: Meta = {
    title: 'Scenes-App/Inbox/Tabs',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-11',
        testOptions: { waitForLoadersToDisappear: false },
    },
}
export default meta

type Story = StoryObj

export const Reports: Story = {
    render: () => (
        <div className="bg-primary min-h-screen">
            <ReportsTab reports={reportTabReports} />
        </div>
    ),
}

export const ReportsEmpty: Story = {
    render: () => (
        <div className="bg-primary min-h-screen">
            <ReportsTab reports={[]} />
        </div>
    ),
}

export const PullRequests: Story = {
    render: () => (
        <div className="bg-primary min-h-screen">
            <PullRequestsTab reports={pullRequestReports} />
        </div>
    ),
}

export const PullRequestsEmpty: Story = {
    render: () => (
        <div className="bg-primary min-h-screen">
            <PullRequestsTab reports={[]} />
        </div>
    ),
}

export const RunsManyAgents: Story = {
    render: () => (
        <div className="bg-primary min-h-screen">
            <RunsTab reports={runReportsMany} />
        </div>
    ),
}

export const RunsFewAgents: Story = {
    render: () => (
        <div className="bg-primary min-h-screen">
            <RunsTab reports={runReportsFew} />
        </div>
    ),
}

export const RunsEmpty: Story = {
    render: () => (
        <div className="bg-primary min-h-screen">
            <RunsTab reports={[]} />
        </div>
    ),
}
