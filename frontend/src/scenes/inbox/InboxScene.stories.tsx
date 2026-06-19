import type { Meta, StoryObj } from '@storybook/react'

import { waitFor } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

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

// The active-filters banner shown above the list when a filter is set. Driven via the search input
// because `searchQuery` is the one filter that isn't persisted to localStorage, so it can't leak into
// the other stories' snapshots the way a persisted source/priority filter would.
export const ActiveFiltersBanner: Story = {
    play: async () => {
        const searchInput = await waitFor(() => {
            const el = document.querySelector<HTMLInputElement>('input[placeholder^="Search by title"]')
            if (!el) {
                throw new Error('Inbox search input not found')
            }
            return el
        })
        await userEvent.type(searchInput, 'checkout')
        await waitFor(() => {
            if (!document.body.textContent?.includes('some reports may be hidden')) {
                throw new Error('Active-filters banner did not render')
            }
        })
    },
}
