import type { Meta, StoryObj } from '@storybook/react'
import { waitFor, within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'
import { router } from 'kea-router'

import { useStorybookMocks } from '~/mocks/browser'
import { FileSystemEntry } from '~/queries/schema/schema-general'

import { ReportsScene } from './ReportsScene'

const meta: Meta<typeof ReportsScene> = {
    title: 'Scenes-App/Reports',
    component: ReportsScene,
    parameters: {
        layout: 'fullscreen',
        mockDate: '2026-01-15',
        featureFlags: [],
        testOptions: { viewport: { width: 1280, height: 800 } },
    },
    render: (_, { parameters }) => {
        let files: FileSystemEntry[] = [
            { id: 'sales', path: 'Sales', type: 'folder', user_access_level: 'editor' },
            { id: 'product', path: 'Product', type: 'folder', user_access_level: 'editor' },
            { id: 'growth', path: 'Sales/Growth', type: 'folder', user_access_level: 'editor' },
            {
                id: 'weekly',
                path: 'Sales/Weekly overview',
                type: 'dashboard',
                ref: '1',
                href: '/dashboard/1',
                user_access_level: 'editor',
            },
            {
                id: 'activation',
                path: 'Product/Activation',
                type: 'insight',
                ref: 'demo0001',
                href: '/insights/demo0001',
                user_access_level: 'editor',
            },
            {
                id: 'notes',
                path: 'Sales/Metric definitions',
                type: 'notebook',
                ref: 'demo0002',
                href: '/notebooks/demo0002',
                user_access_level: 'editor',
            },
        ]
        if (parameters.empty) {
            files = []
        }
        useStorybookMocks({
            get: {
                '/api/:projectScope/:projectId/file_system/unfiled/': [200, { count: 0, results: [] }],
                '/api/:projectScope/:projectId/file_system/': ({ request }) => {
                    if (parameters.failFolders) {
                        return [503, { detail: 'Unavailable' }]
                    }
                    const url = new URL(request.url)
                    const parent = url.searchParams.get('parent') ?? ''
                    const search = url.searchParams.get('search')
                    const results = files.filter((entry) =>
                        search
                            ? entry.path.toLowerCase().includes(search.toLowerCase())
                            : entry.path.split('/').slice(0, -1).join('/') === parent
                    )
                    return [200, { count: results.length, next: null, results, users: [] }]
                },
            },
            post: {
                '/api/:projectScope/:projectId/file_system/': async ({ request }) => {
                    const entry = {
                        ...((await request.json()) as FileSystemEntry),
                        id: `folder-${files.length}`,
                        user_access_level: 'editor',
                    }
                    files = [...files, entry]
                    return [201, entry]
                },
            },
            patch: {
                '/api/:projectScope/:projectId/file_system/:id/': async ({ request, params }) => {
                    const update = (await request.json()) as Partial<FileSystemEntry>
                    const original = files.find((file) => file.id === params.id)
                    if (!original) {
                        return [404, { detail: 'File not found' }]
                    }
                    const entry = { ...original, ...update }
                    files = files.map((file) => (file.id === params.id ? entry : file))
                    return [200, entry]
                },
            },
        })
        return (
            // A docked side panel leaves about 520px for the scene.
            <div className={parameters.narrow ? 'h-screen w-[520px] max-w-full p-4' : 'h-screen p-4'}>
                <ReportsScene />
            </div>
        )
    },
}
export default meta

export const Folders: StoryObj<typeof ReportsScene> = {}
export const EmptyFolder: StoryObj<typeof ReportsScene> = { parameters: { empty: true } }
export const FolderError: StoryObj<typeof ReportsScene> = { parameters: { failFolders: true } }
export const NestedFolder: StoryObj<typeof ReportsScene> = {
    parameters: { narrow: true },
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        const folder = await canvas.findByRole('treeitem', { name: 'tree item: Sales' })
        folder.focus()
        await userEvent.keyboard('{Enter}')
        await waitFor(() => {
            if (router.values.searchParams.folder !== 'Sales') {
                throw new Error('The folder did not open')
            }
        })
    },
}
