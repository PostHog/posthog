import { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { CanvasApi, CanvasViewResponseApi } from '../generated/api.schemas'

const CANVAS_ID = '0190aaaa-0000-7000-8000-000000000001'
const SPACE_ID = '0190aaaa-0000-7000-8000-0000000000aa'
const TASK_ID = '0190aaaa-0000-7000-8000-0000000000bb'

const canvas: CanvasApi = {
    id: CANVAS_ID,
    name: 'Untitled canvas',
    kind: 'freeform',
    description: '',
    channel: SPACE_ID,
    template_id: 'freeform',
    generation_task_id: null,
    pinned: false,
    pinned_at: null,
    current_version_id: null,
    published_build_id: null,
    component_meta: null,
    created_by: { id: 1, uuid: 'user-uuid', email: 'someone@example.com' } as CanvasApi['created_by'],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    url: `https://app.example.com/canvases/${CANVAS_ID}`,
}

function viewResponse(overrides: Partial<CanvasApi> = {}): CanvasViewResponseApi {
    return {
        canvas: { ...canvas, ...overrides },
        published_build: null,
        current_version_id: null,
        has_active_build: false,
        source: null,
        layout: null,
        sandbox_document_url: null,
    }
}

function mocks(view: CanvasViewResponseApi): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/projects/:team_id/canvases/:id/view/': view,
            '/api/projects/:team_id/canvases/:id/builds/': {
                published_build_id: null,
                current_version_id: null,
                builds: [],
            },
            '/api/projects/:team_id/task_channels/:id/': { id: SPACE_ID, name: 'me', system_role: 'personal' },
            '/api/projects/:team_id/tasks/:id/': {
                id: TASK_ID,
                title: 'Weekly active users',
                latest_run: { status: 'in_progress' },
            },
        },
    })
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Canvas',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        pageUrl: urls.canvasDetail(CANVAS_ID),
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV],
        testOptions: { viewport: { width: 1300, height: 900 } },
    },
}
export default meta

type Story = StoryObj<{}>

export const Empty: Story = {
    decorators: [mocks(viewResponse())],
}

export const Generating: Story = {
    decorators: [mocks(viewResponse({ name: 'Weekly active users', generation_task_id: TASK_ID }))],
}

export const NewCanvas: Story = {
    parameters: { pageUrl: urls.canvasNew(SPACE_ID) },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/task_channels/': [
                    { id: 'space-personal', name: 'me', system_role: 'personal' },
                    { id: SPACE_ID, name: 'growth', system_role: null },
                ],
            },
        }),
    ],
}
