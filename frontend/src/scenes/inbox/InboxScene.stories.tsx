import type { Meta, StoryObj } from '@storybook/react'

import { mswDecorator } from '~/mocks/browser'

import {
    allReports,
    mockArtefacts,
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
        '/api/projects/:id/tasks/:taskId': (req) => [200, mockTask(req.params.taskId as string)],
        '/api/projects/:id/signals/source_configs': () => [200, mockSourceConfigs],
        '/api/projects/:id/signals/scout/configs': () => [200, []],
        '/api/projects/:id/signals/scout/runs': () => [200, []],
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

// Set up (sources enabled) but no reports yet – exercises the empty list states.
export const Empty: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports': () => [200, { results: [], count: 0, next: null, previous: null }],
                '/api/projects/:id/signals/source_configs': () => [200, mockSourceConfigs],
                '/api/projects/:id/signals/scout/configs': () => [200, []],
            },
        }),
    ],
}

// Fresh project: nothing watching and nothing in the inbox → the single-command takeover.
export const SelfDrivingOnboarding: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports': () => [200, { results: [], count: 0, next: null, previous: null }],
                '/api/projects/:id/signals/source_configs': () => [200, { results: [], count: 0 }],
                '/api/projects/:id/signals/scout/configs': () => [200, []],
            },
        }),
    ],
}

// Had self-driving before (reports exist) but nothing is watching now → the sleek re-enable banner
// over the normal inbox, so existing work stays accessible. Reports are mocked explicitly (not
// inherited) so "existing work" is unambiguous and the banner – not the takeover – is shown.
export const SelfDrivingPaused: Story = {
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:id/signals/reports': () => [
                    200,
                    { results: allReports, count: allReports.length, next: null, previous: null },
                ],
                '/api/projects/:id/signals/source_configs': () => [200, { results: [], count: 0 }],
                '/api/projects/:id/signals/scout/configs': () => [200, []],
            },
        }),
    ],
}
