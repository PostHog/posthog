import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import {
    allReports,
    mockArtefacts,
    mockReportTasks,
    mockReviewers,
    mockSignals,
    mockSourceConfigs,
    mockTask,
} from './__mocks__/inboxMocks'
import { InboxScene } from './InboxScene'

// Full Inbox scene with a populated report list. Use this to polish the holistic
// layout: header, tab bar + single border, scope picker, filter bar, and the
// centered list column. Switch tabs / scope inside the story to exercise each view.

const sceneMocks = mswDecorator({
    get: {
        '/api/projects/:id/signals/reports': () => [
            200,
            { results: allReports, count: allReports.length, next: null, previous: null },
        ],
        '/api/projects/:id/signals/reports/available_reviewers': () => [200, mockReviewers],
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
        '/api/projects/:id/tasks/:taskId': (req) => [200, mockTask(req.params.taskId as string)],
        '/api/projects/:id/signals/source_configs': () => [200, mockSourceConfigs],
        '/api/projects/:id/external_data_sources': () => [200, { results: [], count: 0 }],
        '/api/projects/:id/external_data_sources/': () => [200, { results: [], count: 0 }],
    },
})

const meta: Meta = {
    title: 'Scenes-App/Inbox/Scene',
    component: InboxScene,
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-06-11',
        // The scene shell keeps a loader element mounted past the VR wait window, so don't block on it.
        testOptions: { waitForLoadersToDisappear: false },
    },
    decorators: [sceneMocks],
}
export default meta

type Story = StoryObj

export const Inbox: Story = {}

export const Empty: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports': () => [200, { results: [], count: 0, next: null, previous: null }],
                '/api/projects/:id/signals/source_configs': () => [200, { results: [], count: 0 }],
            },
        }),
    ],
}
