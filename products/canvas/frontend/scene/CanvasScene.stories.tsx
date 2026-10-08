import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { Meta, StoryObj } from '@storybook/react'
import { waitFor } from '@testing-library/dom'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import { expect, userEvent } from 'storybook/test'

import type { CanvasApi, CanvasBuildApi, CanvasVersionApi, CanvasViewResponseApi } from '../generated/api.schemas'

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
    created_by: {
        id: MOCK_DEFAULT_USER.id,
        uuid: MOCK_DEFAULT_USER.uuid,
        email: MOCK_DEFAULT_USER.email,
    } as CanvasApi['created_by'],
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

const versions: CanvasVersionApi[] = [
    {
        id: 'version-2',
        parent_version_id: 'version-1',
        prompt: 'Split the chart by plan',
        task_id: TASK_ID,
        draft: false,
        created_by: canvas.created_by,
        created_at: '2026-01-02T00:00:00Z',
    },
    {
        id: 'version-1',
        parent_version_id: null,
        prompt: 'A chart of weekly active users',
        task_id: TASK_ID,
        draft: false,
        created_by: canvas.created_by,
        created_at: '2026-01-01T00:00:00Z',
    },
]

const liveBuild: CanvasBuildApi = {
    id: 'build-2',
    source_version_id: 'version-2',
    build_status: 'ready',
    diagnostics: [],
    integrity: null,
    artifact_url: 'about:blank',
    pinned: false,
    created_at: '2026-01-02T00:00:00Z',
    finished_at: '2026-01-02T00:01:00Z',
}

function canvasComment(
    id: string,
    content: string,
    createdAt: string,
    itemContext: Record<string, unknown>,
    sourceComment: string | null = null
): Record<string, unknown> {
    return {
        id,
        content,
        rich_content: null,
        version: 0,
        created_at: createdAt,
        created_by: canvas.created_by,
        scope: 'canvas',
        item_id: CANVAS_ID,
        item_context: itemContext,
        source_comment: sourceComment,
        is_task: false,
        completed_at: null,
        completed_by: null,
    }
}

const QUOTE = 'Weekly active users'
const comments = [
    canvasComment('comment-1', 'Can we split this by plan?', '2026-01-02T00:05:00Z', {
        anchor: { kind: 'text', quote: QUOTE, prefix: '', suffix: '', start: 0, end: QUOTE.length },
        canvasVersionId: 'version-2',
        taskId: TASK_ID,
    }),
    canvasComment(
        'comment-2',
        'Yes, I will add it to the next version.',
        '2026-01-02T00:07:00Z',
        { taskId: TASK_ID },
        'comment-1'
    ),
]

const PERSONAL_SPACE = { id: SPACE_ID, name: 'me', system_role: 'personal', channel_type: 'personal' }

function mocks(
    view: CanvasViewResponseApi,
    threadComments: Record<string, unknown>[] = [],
    space: Record<string, unknown> = PERSONAL_SPACE
): ReturnType<typeof mswDecorator> {
    const built = !!view.published_build
    return mswDecorator({
        get: {
            '/api/projects/:team_id/canvases/:id/view/': view,
            '/api/projects/:team_id/canvases/:id/builds/': {
                published_build_id: view.published_build?.id ?? null,
                current_version_id: view.current_version_id,
                builds: built ? [liveBuild] : [],
            },
            '/api/projects/:team_id/task_channels/:id/': space,
            '/api/projects/:team_id/canvases/:id/versions/': {
                count: built ? versions.length : 0,
                next: null,
                previous: null,
                results: built ? versions : [],
            },
            '/api/projects/:team_id/canvases/:id/drafts/': [],
            '/api/projects/:team_id/comments/': { next: null, previous: null, results: threadComments },
            '/api/projects/:team_id/tasks/:id/': {
                id: TASK_ID,
                title: 'Weekly active users',
                latest_run: { id: 'run-1', status: built ? 'completed' : 'in_progress' },
            },
        },
    })
}

const meta: Meta = {
    component: App,
    title: 'Scenes-App/Canvas',
    tags: ['test-skip'],
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
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
            waitForSelector: '[data-attr="canvas-generating-view-task"]',
        },
    },
    decorators: [mocks(viewResponse({ name: 'Weekly active users', generation_task_id: TASK_ID }))],
}

export const Built: Story = {
    decorators: [
        mocks({
            ...viewResponse({
                name: 'Weekly active users',
                generation_task_id: TASK_ID,
                current_version_id: 'version-2',
                published_build_id: liveBuild.id,
            }),
            published_build: liveBuild,
            current_version_id: 'version-2',
        }),
    ],
}

export const BuiltPublicByTeammate: Story = {
    decorators: [
        mocks(
            {
                ...viewResponse({
                    name: 'Weekly active users',
                    generation_task_id: TASK_ID,
                    current_version_id: 'version-2',
                    published_build_id: liveBuild.id,
                    created_by: {
                        id: 1,
                        uuid: 'teammate-uuid',
                        first_name: 'Sam',
                        email: 'sam@example.com',
                    } as CanvasApi['created_by'],
                }),
                published_build: liveBuild,
                current_version_id: 'version-2',
            },
            [],
            { id: SPACE_ID, name: 'general', system_role: 'general', channel_type: 'public' }
        ),
    ],
}

export const BuiltWithTimeline: Story = {
    ...Built,
    parameters: { pageUrl: `${urls.canvasDetail(CANVAS_ID)}#panel=canvas-timeline` },
}

export const NewCanvas: Story = {
    parameters: { pageUrl: urls.canvasNew(SPACE_ID) },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/task_channels/': [
                    { id: 'space-personal', name: 'me', system_role: 'personal', channel_type: 'personal' },
                    { id: SPACE_ID, name: 'general', system_role: 'general', channel_type: 'public' },
                ],
            },
        }),
    ],
}

export const BuiltWithComments: Story = {
    decorators: [
        mocks(
            {
                ...viewResponse({
                    name: 'Weekly active users',
                    generation_task_id: TASK_ID,
                    current_version_id: 'version-2',
                    published_build_id: liveBuild.id,
                }),
                published_build: liveBuild,
                current_version_id: 'version-2',
            },
            comments
        ),
    ],
    play: async ({ canvasElement }) => {
        await waitFor(
            async () => {
                const menu = canvasElement.querySelector<HTMLElement>('[data-attr="canvas-comments-menu"]')
                expect(menu).not.toBeNull()
                await userEvent.click(menu!)
                expect(document.querySelector('[data-attr="canvas-comments-menu-thread"]')).not.toBeNull()
            },
            { timeout: 15_000 }
        )
    },
}
