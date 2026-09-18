import { fileSystemList } from '~/generated/core/api'
import type { FileSystemApi } from '~/generated/core/api.schemas'

import {
    mcpServerInstallationsAvailableToolsRetrieve,
    mcpServerInstallationsCallToolCreate,
} from 'products/mcp_store/frontend/generated/api'
import {
    notebooksCreate,
    notebooksDestroy,
    notebooksList,
    notebooksRetrieve,
} from 'products/notebooks/frontend/generated/api'
import type { NotebookApi } from 'products/notebooks/frontend/generated/api.schemas'

import { PosthogCommands } from './posthogCommands'
import { PosthogFilesystem } from './posthogFilesystem'

jest.mock('~/generated/core/api', () => ({ fileSystemList: jest.fn() }))
jest.mock('products/notebooks/frontend/generated/api', () => ({
    notebooksList: jest.fn(),
    notebooksRetrieve: jest.fn(),
    notebooksDestroy: jest.fn(),
    notebooksCreate: jest.fn(),
}))
jest.mock('products/mcp_store/frontend/generated/api', () => ({
    mcpServerInstallationsAvailableToolsRetrieve: jest.fn(),
    mcpServerInstallationsCallToolCreate: jest.fn(),
}))

describe('PostHog terminal commands', () => {
    let commands: PosthogCommands
    let filesystem: PosthogFilesystem
    const cwd = '/posthog/files/Research'

    beforeEach(async () => {
        jest.clearAllMocks()
        jest.mocked(fileSystemList).mockResolvedValue({
            count: 1,
            next: null,
            results: [
                {
                    id: 'fs-note',
                    ref: 'short-note',
                    type: 'notebook',
                    path: 'Research/Notes',
                    user_access_level: 'editor',
                } as FileSystemApi,
            ],
        })
        jest.mocked(notebooksList).mockResolvedValue({
            count: 1,
            next: null,
            results: [
                {
                    id: '01900000-0000-7000-8000-000000000002',
                    short_id: 'short-note',
                    title: 'Notes',
                    deleted: false,
                    user_access_level: 'editor',
                    created_at: '2026-01-01T00:00:00Z',
                    created_by: null,
                    last_modified_at: '2026-01-01T00:00:00Z',
                    last_modified_by: null,
                },
            ],
        })
        jest.mocked(notebooksRetrieve).mockResolvedValue({ short_id: 'short-note', title: 'Notes' } as NotebookApi)
        jest.mocked(notebooksDestroy).mockResolvedValue(undefined)
        jest.mocked(notebooksCreate).mockResolvedValue({ short_id: 'new-note' } as NotebookApi)
        jest.mocked(mcpServerInstallationsAvailableToolsRetrieve).mockResolvedValue({
            servers: [
                {
                    installation_id: 'server-id',
                    slug: 'example',
                    name: 'Example',
                    tools: [
                        {
                            name: 'echo',
                            description: 'Echo arguments',
                            input_schema: { type: 'object', properties: { text: { type: 'string' } } },
                            approval_state: 'approved',
                            annotations: { readOnlyHint: true },
                        },
                    ],
                },
            ],
        })
        jest.mocked(mcpServerInstallationsCallToolCreate).mockResolvedValue({
            content: [],
            is_error: false,
            structured_content: { echoed: true },
        })
        const signal = new AbortController().signal
        filesystem = new PosthogFilesystem('42', signal)
        await filesystem.load()
        commands = new PosthogCommands('42', signal, filesystem)
    })

    it('resolves file paths and aliases without reading object bodies to discover IDs', async () => {
        await expect(commands.execute(['notebook-delete', './Notes.md'], cwd)).resolves.toEqual({
            deleted: 'short-note',
        })
        expect(notebooksDestroy).toHaveBeenCalledWith(
            '42',
            'short-note',
            expect.objectContaining({ signal: expect.any(AbortSignal) })
        )
        expect(notebooksRetrieve).not.toHaveBeenCalled()
        expect(mcpServerInstallationsAvailableToolsRetrieve).not.toHaveBeenCalled()
        await expect(commands.execute(['dashboard-get', './Notes.md'], cwd)).rejects.toThrow('Expected a dashboard')
    })

    it('parses typed flags while preserving strings and rejects unknown arguments before making API calls', async () => {
        await commands.execute(['notebooks-list', '--limit', '10'], cwd)
        expect(notebooksList).toHaveBeenLastCalledWith('42', { limit: 10 }, expect.anything())
        await commands.execute(['notebook-create', '--title', 'true', '--markdown', '# café 🦔\nbody'], cwd)
        expect(notebooksCreate).toHaveBeenCalledWith(
            '42',
            expect.objectContaining({ title: 'true', text_content: '# true\n\n# café 🦔\nbody' }),
            expect.anything()
        )
        await expect(
            commands.execute(['notebook-delete', '--json', '{"short_id":"short-note","project_id":"99"}'], cwd)
        ).rejects.toThrow()
        expect(notebooksDestroy).not.toHaveBeenCalled()
        await expect(commands.execute(['notebooks-list', '--limti', '10'], cwd)).rejects.toThrow('Unknown argument')
    })

    it('discovers connected MCP tools and exposes their schemas as files', async () => {
        const tools = await commands.execute(['tools', 'echo'], cwd)
        expect(tools).toEqual([{ name: 'example/echo', description: 'Echo arguments', readOnly: true }])
        const schema = filesystem.root.children!.get('tools')!.children!.get('example%2Fecho.json')!
        expect(
            JSON.parse(new TextDecoder().decode((await schema.open!()).bytes)).inputSchema.properties.text.type
        ).toBe('string')
        await expect(commands.execute(['example/echo', '--text', 'false'], cwd)).resolves.toEqual({ echoed: true })
        expect(mcpServerInstallationsCallToolCreate).toHaveBeenCalledWith(
            '42',
            'server-id',
            { tool_name: 'echo', arguments: { text: 'false' } },
            expect.anything()
        )
        jest.mocked(mcpServerInstallationsCallToolCreate).mockResolvedValue({
            content: [{ type: 'text', text: 'Tool failed' }],
            is_error: true,
        })
        await expect(commands.execute(['example/echo', '--text', 'hello'], cwd)).rejects.toThrow('Tool failed')
    })

    it('returns an error envelope through the filesystem bridge rather than a stale successful result', async () => {
        const directory = filesystem.root.children!.get('.ph')!
        const request = await directory.children!.get('request')!.open!()
        const response = directory.children!.get('response')!
        const read = async (): Promise<unknown> => JSON.parse(new TextDecoder().decode((await response.open!()).bytes))
        await request.save!(new TextEncoder().encode(JSON.stringify({ argv: ['notebook-get', './Notes.md'], cwd })))
        expect(await read()).toMatchObject({ ok: true, result: { short_id: 'short-note' } })
        await request.save!(new TextEncoder().encode('{invalid'))
        expect(await read()).toMatchObject({ ok: false })
        jest.mocked(notebooksRetrieve).mockRejectedValue(new Error('Not allowed'))
        await request.save!(new TextEncoder().encode(JSON.stringify({ argv: ['notebook-get', './Notes.md'], cwd })))
        expect(await read()).toEqual({ ok: false, error: 'Not allowed' })
    })
})
