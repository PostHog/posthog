import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { TerminalScene } from './TerminalScene'

const meta: Meta<typeof TerminalScene> = {
    title: 'Scenes-App/Terminal',
    component: TerminalScene,
    parameters: { layout: 'padded' },
    render: () => {
        const notebook = {
            id: '01900000-0000-7000-8000-000000000002',
            short_id: 'demo-note',
            title: 'Welcome',
            content: {
                type: 'doc',
                content: [
                    {
                        type: 'ph-markdown-notebook',
                        attrs: { markdown: '# Welcome\n\nExplore PostHog with ordinary Unix tools.\n' },
                    },
                ],
            },
            version: 1,
            user_access_level: 'editor',
        }
        const notebooks = new Map([[notebook.short_id, notebook]])
        useStorybookMocks({
            get: {
                '/api/projects/:projectId/file_system/': () => [
                    200,
                    {
                        count: notebooks.size,
                        next: null,
                        results: [...notebooks.values()].map((item) => ({
                            id: item.id,
                            path: `Research/${item.title}`,
                            type: 'notebook',
                            ref: item.short_id,
                            user_access_level: 'editor',
                        })),
                    },
                ],
                '/api/projects/:projectId/notebooks/': () => [
                    200,
                    {
                        count: notebooks.size,
                        next: null,
                        results: [...notebooks.values()].map(({ short_id, title, user_access_level }) => ({
                            short_id,
                            title,
                            user_access_level,
                        })),
                    },
                ],
                '/api/projects/:projectId/notebooks/:shortId/': ({ params }) =>
                    notebooks.has(String(params.shortId))
                        ? [200, notebooks.get(String(params.shortId))]
                        : [404, { detail: 'Not found' }],
                '/api/projects/:projectId/mcp_server_installations/available_tools/': () => [
                    200,
                    {
                        servers: [
                            {
                                installation_id: '01900000-0000-7000-8000-000000000003',
                                name: 'Demo',
                                slug: 'demo',
                                tools: [
                                    {
                                        name: 'echo',
                                        description: 'Echo a message for this demo.',
                                        input_schema: {
                                            type: 'object',
                                            properties: { text: { type: 'string' } },
                                            required: ['text'],
                                        },
                                        annotations: { readOnlyHint: true },
                                        approval_state: 'approved',
                                    },
                                ],
                            },
                        ],
                    },
                ],
            },
            post: {
                '/api/projects/:projectId/notebooks/': async ({ request }) => {
                    const body = (await request.json()) as typeof notebook
                    const created = {
                        ...notebook,
                        ...body,
                        id: '01900000-0000-7000-8000-000000000004',
                        short_id: 'demo-created',
                    }
                    notebooks.set(created.short_id, created)
                    return [201, created]
                },
                '/api/projects/:projectId/mcp_server_installations/:id/call_tool/': async ({ request }) => {
                    const body = (await request.json()) as { arguments: { text: string } }
                    return [200, { content: [], structured_content: { echo: body.arguments.text }, is_error: false }]
                },
            },
            delete: {
                '/api/projects/:projectId/notebooks/:shortId/': ({ params }) => {
                    notebooks.delete(String(params.shortId))
                    return [204, null]
                },
            },
            patch: {
                '/api/projects/:projectId/notebooks/:shortId/': async ({ request, params }) => {
                    const existing = notebooks.get(String(params.shortId))
                    if (!existing) {
                        return [404, { detail: 'Not found' }]
                    }
                    const update = (await request.json()) as typeof notebook
                    if (update.version !== existing.version) {
                        return [409, { detail: 'The notebook changed. Reopen it before saving.' }]
                    }
                    const updated = { ...existing, ...update, version: existing.version + 1 }
                    notebooks.set(updated.short_id, updated)
                    return [200, updated]
                },
            },
        })
        return <TerminalScene />
    },
}
export default meta

export const Default: StoryObj<typeof TerminalScene> = {}
export const Narrow: StoryObj<typeof TerminalScene> = {
    decorators: [
        (Story) => (
            <div className="max-w-lg">
                <Story />
            </div>
        ),
    ],
}
