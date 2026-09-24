import { waitFor } from '@testing-library/react'

import { fileSystemList } from '~/generated/core/api'
import type { FileSystemApi } from '~/generated/core/api.schemas'
import { performQuery } from '~/queries/query'

import {
    mcpServerInstallationsAvailableToolsRetrieve,
    mcpServerInstallationsCallToolCreate,
} from 'products/mcp_store/frontend/generated/api'
import {
    notebooksCreate,
    notebooksList,
    notebooksPartialUpdate,
    notebooksRetrieve,
} from 'products/notebooks/frontend/generated/api'
import type { NotebookApi } from 'products/notebooks/frontend/generated/api.schemas'
import { insightsRetrieve } from 'products/product_analytics/frontend/generated/api'

import { PosthogCommands } from './posthogCommands'
import { PosthogFilesystem } from './posthogFilesystem'
import { MAX_TERMINAL_FILE_BYTES } from './terminalFilesystem'

jest.mock('scenes/teamLogic', () => ({ teamLogic: { values: { currentTeamId: 42 } } }))
jest.mock('~/queries/query', () => ({ performQuery: jest.fn() }))

jest.mock('~/generated/core/api', () => ({ fileSystemList: jest.fn() }))
jest.mock('products/notebooks/frontend/generated/api', () => ({
    notebooksList: jest.fn(),
    notebooksRetrieve: jest.fn(),
    notebooksPartialUpdate: jest.fn(),
    notebooksCreate: jest.fn(),
}))
jest.mock('products/mcp_store/frontend/generated/api', () => ({
    mcpServerInstallationsAvailableToolsRetrieve: jest.fn(),
    mcpServerInstallationsCallToolCreate: jest.fn(),
}))
jest.mock('products/product_analytics/frontend/generated/api', () => ({
    insightsRetrieve: jest.fn(),
    insightsList: jest.fn(),
}))

describe('PostHog terminal commands', () => {
    const confirm = jest.fn(async () => true)
    let commands: PosthogCommands
    let filesystem: PosthogFilesystem
    const navigate = jest.fn()
    const cwd = '/posthog/files/Research'
    const author = {
        id: 1,
        uuid: '01900000-0000-7000-8000-000000000001',
        email: 'author@example.com',
        hedgehog_config: null,
    }

    it.each([
        ['--markdown', '| answer |\n| --- |\n| 42 |'],
        ['--csv', 'answer\n42'],
        ['--tsv', 'answer\n42'],
        ['--json', { columns: ['answer'], results: [[42]], types: ['Int64'], hasMore: true }],
    ])('runs local SQL with %s output', async (format, expected) => {
        jest.mocked(performQuery).mockResolvedValue({
            columns: ['answer'],
            results: [[42]],
            types: ['Int64'],
            hasMore: true,
        })
        expect(await commands.execute(['run', '/tmp/report.sql', 'select 42 as answer', format], cwd)).toEqual(expected)
        expect(performQuery).toHaveBeenCalledWith(
            expect.objectContaining({ kind: 'HogQLQuery', query: 'select 42 as answer' }),
            expect.objectContaining({ signal: expect.any(AbortSignal) }),
            'force_blocking'
        )
    })

    it.each(['--csv', '--tsv'])(
        'escapes spreadsheet formulas in %s exports while preserving numbers',
        async (format) => {
            jest.mocked(performQuery).mockResolvedValue({
                columns: ['=header'],
                results: [['=1+1'], ['+1+1'], ['-1+1'], ['@SUM(1)'], ['\t=1+1'], ['\r=1+1'], [-42], [null], ['a"b']],
            })
            expect(await commands.execute(['run', '/tmp/report.sql', 'select value', format], cwd)).toBe(
                [
                    '"\'=header"',
                    '"\'=1+1"',
                    '"\'+1+1"',
                    '"\'-1+1"',
                    '"\'@SUM(1)"',
                    '"\'\t=1+1"',
                    '"\'\r=1+1"',
                    '-42',
                    '',
                    '"a""b"',
                ].join('\n')
            )
        }
    )

    it('completes aliases and JSON arguments without invoking commands', async () => {
        expect(await commands.execute(['_complete', '1', 'op', 'ph', ''], cwd)).toBe('open')
        expect(await commands.execute(['_complete', '1', 'notebook-g', 'ph', ''], cwd)).toBe('notebook-get')
        expect(await commands.execute(['_complete', '2', '--ti', 'notebook-create', 'notebook-create'], cwd)).toBe(
            '--title'
        )
        expect(await commands.execute(['_complete', '2', '--j', 'notebook-create', 'notebook-create'], cwd)).toBe(
            '--json'
        )
        expect(await commands.execute(['_complete', '3', '', '--json', 'notebook-create'], cwd)).toBe('')
        for (const command of ['help', 'tools', 'refresh', 'open']) {
            expect(await commands.execute(['_complete', '2', '--', command, command], cwd)).toBe('')
        }
        expect(notebooksCreate).not.toHaveBeenCalled()
        expect(mcpServerInstallationsCallToolCreate).not.toHaveBeenCalled()
    })

    it.each([
        ['notebook-delete', 'shortnote'],
        ['notebook-update', 'shortnote', '--deleted'],
        ['notebook-update', 'shortnote', '--title', 'Updated'],
        ['notebook-create', '--title', 'New notebook'],
        ['example/echo', '--text', 'hello'],
    ])('blocks %s until the user approves its exact arguments', async (...argv) => {
        let answer!: (approved: boolean) => void
        confirm.mockImplementationOnce(
            () =>
                new Promise<boolean>((resolve) => {
                    answer = resolve
                })
        )
        const operation = commands.execute(argv, cwd)
        const outcome = operation.catch((error: Error) => error)
        await waitFor(() => expect(confirm).toHaveBeenCalledTimes(1))
        expect(notebooksPartialUpdate).not.toHaveBeenCalled()
        expect(notebooksCreate).not.toHaveBeenCalled()
        expect(mcpServerInstallationsCallToolCreate).not.toHaveBeenCalled()
        answer(false)
        await expect(outcome).resolves.toEqual(expect.objectContaining({ message: 'Canceled. No changes made.' }))
        expect(notebooksPartialUpdate).not.toHaveBeenCalled()
        expect(notebooksCreate).not.toHaveBeenCalled()
        expect(mcpServerInstallationsCallToolCreate).not.toHaveBeenCalled()
    })

    beforeEach(async () => {
        jest.clearAllMocks()
        confirm.mockResolvedValue(true)
        jest.mocked(fileSystemList).mockResolvedValue({
            count: 1,
            next: null,
            results: [
                {
                    id: 'fs-note',
                    ref: 'shortnote',
                    type: 'notebook',
                    path: 'Research/Notes',
                    meta: { content_type: 'text/markdown' },
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
                    short_id: 'shortnote',
                    title: 'Notes',
                    deleted: false,
                    user_access_level: 'editor',
                    created_at: '2026-01-01T00:00:00Z',
                    created_by: author,
                    last_modified_at: '2026-01-01T00:00:00Z',
                    last_modified_by: author,
                },
            ],
        })
        jest.mocked(notebooksRetrieve).mockResolvedValue({ short_id: 'shortnote', title: 'Notes' } as NotebookApi)
        jest.mocked(notebooksPartialUpdate).mockResolvedValue({ short_id: 'shortnote', deleted: true } as NotebookApi)
        jest.mocked(notebooksCreate).mockResolvedValue({ short_id: 'newnote' } as NotebookApi)
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
                        {
                            name: 'convert',
                            description: 'Convert arguments',
                            input_schema: {
                                type: 'object',
                                $defs: { Count: { type: 'integer' } },
                                properties: {
                                    dry_run: { anyOf: [{ type: 'boolean' }, { type: 'null' }] },
                                    force: { type: ['boolean', 'null'] },
                                    limit: { $ref: '#/$defs/Count' },
                                    query: { oneOf: [{ type: 'object' }, { type: 'array' }] },
                                    note: { anyOf: [{ type: 'string' }, { type: 'object' }] },
                                },
                            },
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
        filesystem = new PosthogFilesystem('42', signal, confirm, true)
        await filesystem.load()
        commands = new PosthogCommands('42', signal, filesystem, navigate)
    })

    it.each([
        [[], '/files?folder=Research'],
        [['.'], '/files?folder=Research'],
        [['..'], '/files'],
        [['Notes.md'], '/notebooks/shortnote'],
        [['/posthog/api/notebook/shortnote.json'], '/notebooks/shortnote'],
    ])('opens %j in PostHog', async (args, url) => {
        await commands.execute(['open', ...args], cwd)
        expect(navigate).toHaveBeenCalledWith(url)
        expect(notebooksRetrieve).not.toHaveBeenCalled()
        expect(mcpServerInstallationsAvailableToolsRetrieve).not.toHaveBeenCalled()
    })

    it.each([['missing.md'], ['/tmp/local.json'], ['Notes.md', 'another.md']])(
        'does not navigate for invalid open arguments %j',
        async (...args) => {
            await expect(commands.execute(['open', ...args], cwd)).rejects.toThrow()
            expect(navigate).not.toHaveBeenCalled()
        }
    )

    it('does not navigate after the terminal stops while resolving a path', async () => {
        const controller = new AbortController()
        commands = new PosthogCommands('42', controller.signal, filesystem, navigate)
        const opening = commands.execute(['open', 'Notes.md'], cwd)
        controller.abort()
        await expect(opening).rejects.toThrow('terminal stopped')
        expect(navigate).not.toHaveBeenCalled()
    })

    it.each([
        ['notebook-delete', './Notes.md'],
        ['notebooks-destroy', '--short-id', 'shortnote'],
        ['notebook-delete', '--json', '{"short_id":"shortnote"}'],
    ])('soft-deletes a notebook using %s %s', async (...argv) => {
        await expect(commands.execute(argv, cwd)).resolves.toEqual({
            deleted: 'shortnote',
        })
        expect(notebooksPartialUpdate).toHaveBeenCalledWith(
            '42',
            'shortnote',
            { deleted: true },
            expect.objectContaining({ signal: expect.any(AbortSignal) })
        )
        expect(notebooksRetrieve).not.toHaveBeenCalled()
        expect(mcpServerInstallationsAvailableToolsRetrieve).not.toHaveBeenCalled()
        await expect(commands.execute(['dashboard-get', './Notes.md'], cwd)).rejects.toThrow('Expected a dashboard')
    })

    it.each([
        ['notebook-delete', '..'],
        ['notebook-delete', '--short-id', '%2e%2e'],
        ['notebook-delete', '--json', '{"short_id":".."}'],
        ['notebook-update', '..'],
        ['notebook-get', 'shortnote?format=json'],
        ['notebook-get', 'shortnote#'],
        ['notebook-get', 'shortnote\n'],
        ['insight-get', '..\\..\\99\\insights\\42'],
        ['insight-get', '%2e%2e'],
    ])('rejects unsafe object IDs in %s %s before an API request', async (...argv) => {
        await expect(commands.execute(argv, cwd)).rejects.toThrow()
        expect(notebooksPartialUpdate).not.toHaveBeenCalled()
        expect(notebooksRetrieve).not.toHaveBeenCalled()
        expect(insightsRetrieve).not.toHaveBeenCalled()
    })

    it.each([
        ['notebook-get', 'Ab12Cd34'],
        ['notebook-get', 'Café123'],
        ['insight-get', 'Ab12Cd34'],
        ['insight-get', '123456789012345'],
    ])('accepts supported IDs in %s %s', async (command, id) => {
        await commands.execute([command, id], cwd)
        if (command === 'notebook-get') {
            expect(notebooksRetrieve).toHaveBeenCalledWith('42', id, expect.anything())
        } else {
            expect(insightsRetrieve).toHaveBeenCalledWith('42', id, undefined, expect.anything())
        }
    })

    it('validates object IDs resolved from project files', async () => {
        jest.mocked(fileSystemList).mockResolvedValue({
            count: 1,
            next: null,
            results: [
                {
                    id: 'fs-note',
                    ref: '..',
                    type: 'notebook',
                    path: 'Research/Notes',
                    user_access_level: 'editor',
                } as FileSystemApi,
            ],
        })
        await filesystem.load()

        await expect(commands.execute(['notebook-delete', './Notes.json'], cwd)).rejects.toThrow()
        expect(notebooksPartialUpdate).not.toHaveBeenCalled()
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
            commands.execute(['notebook-delete', '--json', '{"short_id":"shortnote","project_id":"99"}'], cwd)
        ).rejects.toThrow()
        expect(notebooksPartialUpdate).not.toHaveBeenCalled()
        await expect(commands.execute(['notebooks-list', '--limti', '10'], cwd)).rejects.toThrow('Unknown argument')
    })

    it('keeps notebook search text in step with a content update', async () => {
        const markdown = '# Notes\n\nrewritten body'
        const content = {
            type: 'doc',
            content: [{ type: 'ph-markdown-notebook', attrs: { nodeId: 'markdown-notebook-v2', markdown } }],
        }
        await commands.execute(['notebook-update', '--json', JSON.stringify({ short_id: 'shortnote', content })], cwd)
        expect(notebooksPartialUpdate).toHaveBeenLastCalledWith(
            '42',
            'shortnote',
            { content, text_content: markdown },
            expect.anything()
        )
        await commands.execute(
            ['notebook-update', '--json', JSON.stringify({ short_id: 'shortnote', content, text_content: 'chosen' })],
            cwd
        )
        expect(notebooksPartialUpdate).toHaveBeenLastCalledWith(
            '42',
            'shortnote',
            { content, text_content: 'chosen' },
            expect.anything()
        )
        jest.mocked(notebooksPartialUpdate).mockClear()
        await expect(
            commands.execute(
                [
                    'notebook-update',
                    '--json',
                    JSON.stringify({ short_id: 'shortnote', content: { type: 'doc', content: [{ type: 'p' }] } }),
                ],
                cwd
            )
        ).rejects.toThrow('Include text_content')
        expect(notebooksPartialUpdate).not.toHaveBeenCalled()
    })

    it('resolves argument types through references, unions and type arrays', async () => {
        await commands.execute(
            ['example/convert', '--dry-run', '--force', '--limit', '10', '--query', '{"kind":"events"}'],
            cwd
        )
        expect(mcpServerInstallationsCallToolCreate).toHaveBeenLastCalledWith(
            '42',
            'server-id',
            {
                tool_name: 'convert',
                arguments: { dry_run: true, force: true, limit: 10, query: { kind: 'events' } },
            },
            expect.anything()
        )
        await commands.execute(['example/convert', '--note', 'plain text'], cwd)
        expect(mcpServerInstallationsCallToolCreate).toHaveBeenLastCalledWith(
            '42',
            'server-id',
            { tool_name: 'convert', arguments: { note: 'plain text' } },
            expect.anything()
        )
        await expect(commands.execute(['example/convert', '--limit', 'ten'], cwd)).rejects.toThrow(
            'Invalid integer value for --limit.'
        )
    })

    it('discovers connected MCP tools and exposes their schemas as files', async () => {
        const tools = await commands.execute(['tools', 'echo'], cwd)
        // The fixture declares readOnlyHint, which the terminal must not repeat as a safety claim.
        expect(tools).toEqual([{ name: 'example/echo', description: 'Echo arguments', readOnly: false }])
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
        expect(await read()).toMatchObject({ ok: true, result: { short_id: 'shortnote' } })
        await request.save!(new TextEncoder().encode('{invalid'))
        expect(await read()).toMatchObject({ ok: false })
        jest.mocked(notebooksRetrieve).mockRejectedValue(new Error('Not allowed'))
        await request.save!(new TextEncoder().encode(JSON.stringify({ argv: ['notebook-get', './Notes.md'], cwd })))
        expect(await read()).toEqual({ ok: false, error: 'Not allowed' })
        jest.mocked(notebooksRetrieve).mockRejectedValue(new Error('x'.repeat(MAX_TERMINAL_FILE_BYTES + 1)))
        await request.save!(new TextEncoder().encode(JSON.stringify({ argv: ['notebook-get', './Notes.md'], cwd })))
        expect((await response.open!()).bytes.length).toBeLessThan(MAX_TERMINAL_FILE_BYTES)
        expect(await read()).toEqual({ ok: false, error: expect.stringContaining('exceeds 4 MiB') })
    })
})
