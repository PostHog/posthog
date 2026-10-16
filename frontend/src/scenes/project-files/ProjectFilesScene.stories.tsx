import type { Meta, StoryObj } from '@storybook/react'
import { router } from 'kea-router'

import { useStorybookMocks } from '~/mocks/browser'

import { ProjectFilesScene } from './ProjectFilesScene'

const meta: Meta<typeof ProjectFilesScene> = {
    title: 'Scenes-App/Files',
    component: ProjectFilesScene,
    parameters: { layout: 'padded' },
    render: (args, { parameters }) => {
        const entries = [
            { id: 'research-folder', path: 'Research', type: 'folder', ref: '', href: '', user_access_level: 'editor' },
            ...Array.from({ length: parameters.fileCount ?? 1 }, (_, index) => ({
                id: `notebook-${index}`,
                path: `Research/${index ? `Notes ${index}` : 'Welcome'}`,
                type: 'notebook',
                ref: `notebook-${index}`,
                href: `/notebooks/notebook-${index}`,
                user_access_level: 'editor',
            })),
        ]
        useStorybookMocks({
            get: {
                '/api/:projectScope/:projectId/file_system/unfiled/': () => [200, { count: 0, results: [] }],
                '/api/:projectScope/:projectId/file_system/': ({ request }) => {
                    const parent = new URL(request.url).searchParams.get('parent')
                    const results = entries.filter((entry) => entry.path.split('/').slice(0, -1).join('/') === parent)
                    return [200, { count: results.length, next: null, results }]
                },
            },
        })
        return (
            <div className="h-[calc(100vh-2rem)]">
                <ProjectFilesScene {...args} />
            </div>
        )
    },
}
export default meta

export const Folder: StoryObj<typeof ProjectFilesScene> = { args: { folder: 'Research' } }
export const ProjectRoot: StoryObj<typeof ProjectFilesScene> = {}
export const FolderFromUrl: StoryObj<typeof ProjectFilesScene> = {
    decorators: [
        (Story) => (
            <div className="w-[800px] max-w-full">
                <Story />
            </div>
        ),
    ],
    play: () => router.actions.push('/files?folder=Research'),
}
export const LongFolder: StoryObj<typeof ProjectFilesScene> = {
    args: { folder: 'Research' },
    parameters: { fileCount: 80 },
}
export const Narrow: StoryObj<typeof ProjectFilesScene> = {
    args: { folder: 'Research' },
    decorators: [
        (Story) => (
            <div className="max-w-lg">
                <Story />
            </div>
        ),
    ],
}
