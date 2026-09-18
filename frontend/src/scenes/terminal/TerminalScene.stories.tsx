import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'

import { TerminalScene } from './TerminalScene'

const meta: Meta<typeof TerminalScene> = {
    title: 'Scenes-App/Terminal',
    component: TerminalScene,
    parameters: { layout: 'padded' },
    render: () => {
        let notebook = {
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
        useStorybookMocks({
            get: {
                '/api/projects/:projectId/file_system/': () => [
                    200,
                    {
                        count: 1,
                        next: null,
                        results: [
                            {
                                id: '01900000-0000-7000-8000-000000000001',
                                path: 'Research/Welcome',
                                type: 'notebook',
                                ref: 'demo-note',
                                user_access_level: 'editor',
                            },
                        ],
                    },
                ],
                '/api/projects/:projectId/notebooks/demo-note/': () => [200, notebook],
            },
            patch: {
                '/api/projects/:projectId/notebooks/demo-note/': async ({ request }) => {
                    const update = (await request.json()) as typeof notebook
                    if (update.version !== notebook.version) {
                        return [409, { detail: 'The notebook changed. Reopen it before saving.' }]
                    }
                    notebook = { ...notebook, ...update, version: notebook.version + 1 }
                    return [200, notebook]
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
