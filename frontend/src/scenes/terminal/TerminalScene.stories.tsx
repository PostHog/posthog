import type { Meta, StoryObj } from '@storybook/react'
import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { Command } from 'lib/components/Command/Command'
import { FEATURE_FLAGS } from 'lib/constants'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'

import { GlobalShortcuts } from '~/layout/GlobalShortcuts'
import { useStorybookMocks } from '~/mocks/browser'

import { expect, spyOn, userEvent, waitFor } from 'storybook/test'

import { TerminalDock } from './TerminalDock'
import { terminalDockLogic } from './terminalDockLogic'
import { terminalLogic } from './terminalLogic'
import { TerminalRuntime } from './terminalRuntime'
import { TerminalScene } from './TerminalScene'
import type { TerminalSession } from './TerminalSession'

function DockedTerminalPreview(): JSX.Element {
    const { location } = useValues(router)
    return (
        <>
            <div className="app-layout">
                <div className="left-nav flex flex-col gap-2 p-4">
                    <LemonButton to="/notebooks/demonote">Notebook page</LemonButton>
                    <LemonButton to="/terminal">Full terminal</LemonButton>
                </div>
                <div className="main-content-container flex min-h-0 flex-col p-4">
                    {removeProjectIdIfPresent(location.pathname) === '/terminal' ? (
                        <TerminalScene />
                    ) : (
                        <p>Press Ctrl+backtick or use Toggle terminal in Cmd+K.</p>
                    )}
                </div>
            </div>
            <GlobalShortcuts />
            <Command />
            <TerminalDock />
        </>
    )
}

const meta: Meta<typeof TerminalScene> = {
    title: 'Scenes-App/Terminal',
    component: TerminalScene,
    parameters: { layout: 'padded', featureFlags: [FEATURE_FLAGS.POSTHOG_TERMINAL] },
    beforeEach: ({ parameters }) => {
        if (parameters.liveRuntime) {
            return
        }
        // Visual snapshots must not depend on firmware downloads or Linux boot timing.
        const start = spyOn(TerminalRuntime.prototype, 'start').mockImplementation(
            async (_server, _signal, onReady) => {
                const { view } = terminalLogic.cache.session as TerminalSession
                view.options.cursorBlink = false
                await new Promise<void>((resolve) =>
                    view.write(
                        'PostHog terminal\r\n\r\n' +
                            '\x1b[32mposthog\x1b[0m:\x1b[34m/posthog/files\x1b[0m $ ls\r\n' +
                            'Objects  Research\r\n' +
                            '\x1b[32mposthog\x1b[0m:\x1b[34m/posthog/files\x1b[0m $ ',
                        resolve
                    )
                )
                onReady()
            }
        )
        return () => start.mockRestore()
    },
    render: (_, { parameters }) => {
        const notebook = {
            id: '01900000-0000-7000-8000-000000000002',
            short_id: 'demonote',
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
        const paths = new Map([[notebook.id, 'Research/Welcome']])
        const folders = new Map([['01900000-0000-7000-8000-000000000005', 'Research']])
        const objects = [
            { type: 'dashboard', route: 'dashboards', ref: '101', name: 'Overview' },
            { type: 'insight', route: 'insights', ref: 'demoinsight', name: 'Signups' },
            { type: 'feature_flag', route: 'feature_flags', ref: '102', name: 'New navigation' },
            { type: 'cohort', route: 'cohorts', ref: '103', name: 'Active users' },
            { type: 'action', route: 'actions', ref: '104', name: 'Checkout' },
            { type: 'survey', route: 'surveys', ref: '01900000-0000-7000-8000-000000000006', name: 'Feedback' },
            { type: 'experiment', route: 'experiments', ref: '105', name: 'Signup test' },
        ]
        const objectData = new Map<string, Record<string, unknown>>(
            objects.map((item) => [
                item.ref,
                { id: item.ref, name: item.name, description: 'Terminal demo', user_access_level: 'editor' },
            ])
        )
        objectData.set('demoinsight', {
            ...objectData.get('demoinsight'),
            query: { kind: 'DataTableNode', source: { kind: 'HogQLQuery', query: 'select 42 as answer' } },
        })
        useStorybookMocks({
            get: {
                '/api/projects/:projectId/insights/': [
                    200,
                    { count: 1, results: [{ short_id: 'demoinsight' }], next: null },
                ],
                ...Object.fromEntries(
                    objects.map((item) => [
                        `/api/projects/:projectId/${item.route}/${item.ref}/`,
                        () => [200, objectData.get(item.ref)],
                    ])
                ),
                '/api/projects/:projectId/file_system/': () => [
                    200,
                    {
                        count: notebooks.size + folders.size + objects.length,
                        next: null,
                        results: [...notebooks.values()]
                            .map((item) => ({
                                id: item.id,
                                path: paths.get(item.id) ?? `Research/${item.title}`,
                                type: 'notebook',
                                ref: item.short_id,
                                user_access_level: 'editor',
                                meta: { content_type: 'text/markdown' },
                            }))
                            .concat(
                                [...folders].map(([id, path]) => ({
                                    id,
                                    path,
                                    type: 'folder',
                                    ref: '',
                                    user_access_level: 'editor',
                                    meta: { content_type: 'inode/directory' },
                                }))
                            )
                            .concat(
                                objects.map((item) => ({
                                    id: `file-${item.ref}`,
                                    path: `Objects/${item.name}`,
                                    type: item.type,
                                    ref: item.ref,
                                    user_access_level: 'editor',
                                    meta: {
                                        content_type: item.type === 'insight' ? 'application/sql' : 'application/json',
                                    },
                                }))
                            ),
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
                '/api/projects/:projectId/query/:queryKind/': [
                    200,
                    { columns: ['answer'], results: [[42]], types: ['Int64'], hasMore: false },
                ],
                '/api/projects/:projectId/file_system/': async ({ request }) => {
                    const { path } = (await request.json()) as { path: string }
                    const id = crypto.randomUUID()
                    folders.set(id, path)
                    return [201, { id, path, type: 'folder', user_access_level: 'editor' }]
                },
                '/api/projects/:projectId/file_system/:id/move/': async ({ request, params }) => {
                    const id = String(params.id)
                    const { new_path } = (await request.json()) as { new_path: string }
                    const oldPath = folders.get(id) ?? paths.get(id)
                    if (!oldPath) {
                        return [404, { detail: 'Not found' }]
                    }
                    for (const entries of [paths, folders]) {
                        for (const [entryId, path] of entries) {
                            if (path === oldPath || path.startsWith(`${oldPath}/`)) {
                                entries.set(entryId, new_path + path.slice(oldPath.length))
                            }
                        }
                    }
                    return [200, { id, path: new_path }]
                },
                '/api/projects/:projectId/notebooks/': async ({ request }) => {
                    const body = (await request.json()) as typeof notebook
                    const created = {
                        ...notebook,
                        ...body,
                        id: '01900000-0000-7000-8000-000000000004',
                        short_id: 'democreated',
                    }
                    notebooks.set(created.short_id, created)
                    paths.set(created.id, `Research/${created.title}`)
                    return [201, created]
                },
                '/api/projects/:projectId/mcp_server_installations/:id/call_tool/': async ({ request }) => {
                    const body = (await request.json()) as { arguments: { text: string } }
                    return [200, { content: [], structured_content: { echo: body.arguments.text }, is_error: false }]
                },
            },
            delete: {
                '/api/projects/:projectId/file_system/:id/': ({ params }) => {
                    const id = String(params.id)
                    const folder = folders.get(id)
                    if (folder !== undefined) {
                        if ([...folders.values(), ...paths.values()].some((path) => path.startsWith(`${folder}/`))) {
                            return [409, { detail: 'Folder is not empty.' }]
                        }
                        folders.delete(id)
                        return [204]
                    }
                    const notebook = [...notebooks.values()].find((item) => item.id === id)
                    if (!notebook) {
                        return [404, { detail: 'Not found' }]
                    }
                    notebooks.delete(notebook.short_id)
                    paths.delete(id)
                    return [204]
                },
                '/api/projects/:projectId/notebooks/:shortId/': ({ params }) => {
                    notebooks.delete(String(params.shortId))
                    return [204, null]
                },
            },
            patch: {
                ...Object.fromEntries(
                    objects.map((item) => [
                        `/api/projects/:projectId/${item.route}/${item.ref}/`,
                        async ({ request }: { request: Request }) => {
                            const data = await request.json()
                            if (typeof data.name !== 'string' || !data.name.trim()) {
                                return [400, { detail: 'Name cannot be empty.' }]
                            }
                            const updated = { ...objectData.get(item.ref), ...data, id: item.ref }
                            objectData.set(item.ref, updated)
                            return [200, updated]
                        },
                    ])
                ),
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
        return parameters.docked ? (
            <DockedTerminalPreview />
        ) : (
            <div className="h-[calc(100vh-2rem)]">
                <TerminalScene />
            </div>
        )
    },
}
export default meta

export const Default: StoryObj<typeof TerminalScene> = {}

export const LiveRuntime: StoryObj<typeof TerminalScene> = {
    tags: ['!test'],
    parameters: { liveRuntime: true },
}
export const Docked: StoryObj<typeof TerminalScene> = {
    parameters: {
        docked: true,
        pageUrl: '/notebooks/demonote',
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.POSTHOG_TERMINAL],
    },
    play: async () => {
        await waitFor(() => expect(terminalDockLogic.isMounted()).toBe(true))
        terminalDockLogic.actions.setDockOpen(true)
        await waitFor(() => expect(terminalLogic.values.status).toBe('ready'))
    },
}
export const DockDisabled: StoryObj<typeof TerminalScene> = {
    parameters: {
        docked: true,
        pageUrl: '/notebooks/demonote',
        layout: 'fullscreen',
        featureFlags: { [FEATURE_FLAGS.POSTHOG_TERMINAL]: false },
    },
}
export const Narrow: StoryObj<typeof TerminalScene> = {
    decorators: [
        (Story) => (
            <div className="max-w-lg">
                <Story />
            </div>
        ),
    ],
}

export const DeleteConfirmation: StoryObj<typeof TerminalScene> = {
    play: async () => {
        await waitFor(() => expect(terminalLogic.values.status).toBe('ready'))
        void terminalLogic.cache.filesystem
            .confirmOperation({
                title: 'Delete PostHog files and folders?',
                description:
                    'Remove 4 files and folders from project 1. Removing the last file reference also deletes the PostHog object. This affects everyone in the project.',
                items: [
                    '/posthog/files/Research/Welcome.md (notebook: demonote)',
                    '/posthog/files/Research/Overview.json (dashboard: 101)',
                    '/posthog/files/Research/Signups.json (insight: demoinsight)',
                    '/posthog/files/Research',
                ],
            })
            .catch(() => {})
        await waitFor(() => expect(document.querySelector('[data-attr="terminal-confirmation"]')).not.toBeNull())
        const approve = document.querySelector<HTMLButtonElement>('[data-attr="terminal-confirmation-approve"]')!
        approve.focus()
        await userEvent.keyboard('{Enter} {Escape}{Tab}')
        approve.click()
        expect(document.querySelector('[data-attr="terminal-confirmation"]')).not.toBeNull()
    },
}

export const Framebuffer: StoryObj<typeof TerminalScene> = {
    parameters: { testOptions: { snapshotTargetSelector: 'body' } },
    play: async () => {
        await waitFor(() => expect(terminalLogic.values.status).toBe('ready'))
        terminalLogic.actions.setDisplayOpen(true)
    },
}

export const LiveDoom: StoryObj<typeof TerminalScene> = {
    tags: ['!test'],
    parameters: { liveRuntime: true },
    play: async () => {
        await waitFor(() => expect(terminalLogic.values.status).toBe('ready'), { timeout: 120_000 })
        window.posthogTerminal?.write('doom\n')
    },
}

export const LiveClassics: StoryObj<typeof TerminalScene> = {
    tags: ['!test'],
    parameters: { liveRuntime: true },
    play: async () => {
        await waitFor(() => expect(terminalLogic.values.status).toBe('ready'), { timeout: 120_000 })
        window.posthogTerminal?.write('figlet PostHog\n')
    },
}
