import type { Decorator, Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import { pullRequestReports, reportTabReports, runReportsFew, runReportsMany } from '../../__mocks__/inboxMocks'
import { SignalReport } from '../../types'
import { PullRequestsTab } from './PullRequestsTab'
import { ReportsTab } from './ReportsTab'
import { RunsTab } from './RunsTab'

// Stories for the inbox tab bodies. The flat report tabs (Reports / Pull requests) load via
// `reportListLogic`, so they get an mswDecorator that mocks the reports list endpoint; the
// Runs tab is prop-driven and receives mock reports directly. Use these to polish list
// density, card design, and the Runs-tab queued / live / finished sections.

// Mocks the shared reports list endpoint so the logic-driven flat tabs render the given set.
function reportsListDecorator(reports: SignalReport[]): Decorator {
    return mswDecorator({
        get: {
            '/api/projects/:id/signals/reports': () => [
                200,
                { results: reports, count: reports.length, next: null, previous: null },
            ],
        },
    })
}

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
    decorators: [reportsListDecorator(reportTabReports)],
    render: () => (
        <div className="bg-primary min-h-screen">
            <ReportsTab />
        </div>
    ),
}

export const ReportsEmpty: Story = {
    decorators: [reportsListDecorator([])],
    render: () => (
        <div className="bg-primary min-h-screen">
            <ReportsTab />
        </div>
    ),
}

export const PullRequests: Story = {
    decorators: [reportsListDecorator(pullRequestReports)],
    render: () => (
        <div className="bg-primary min-h-screen">
            <PullRequestsTab />
        </div>
    ),
}

export const PullRequestsEmpty: Story = {
    decorators: [reportsListDecorator([])],
    render: () => (
        <div className="bg-primary min-h-screen">
            <PullRequestsTab />
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
