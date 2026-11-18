import { spawnSync } from 'child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'

import { PH_SCRIPT, TerminalCommands } from './terminalCommands'
import { TerminalFilesystem } from './terminalFilesystem'

describe('terminal command bridge', () => {
    it.each(['markdown', 'csv', 'tsv', 'json'])(
        'prints %s warnings on stderr without changing stdout',
        async (format) => {
            const result =
                format === 'json'
                    ? { columns: ['answer'], results: [[42]] }
                    : format === 'markdown'
                      ? '| answer |\n| --- |\n| 42 |'
                      : 'answer\n42'
            const filesystem = new TerminalFilesystem()
            new TerminalCommands(filesystem, async (_argv, _cwd, { onWarning }) => {
                onWarning?.('Some insights are excluded.')
                return result
            })
            const bridge = filesystem.root.children!.get('.ph')!.children!
            const request = await bridge.get('request')!.open!()
            await request.save!(new TextEncoder().encode(JSON.stringify({ argv: ['hogql'], cwd: '/tmp' })))
            const response = (await bridge.get('response')!.open!()).bytes
            expect(JSON.parse(new TextDecoder().decode(response))).toEqual({
                ok: true,
                result,
                warnings: ['Some insights are excluded.'],
            })
            const directory = mkdtempSync(join(tmpdir(), 'terminal-command-'))
            try {
                writeFileSync(join(directory, 'response'), response)
                const command = spawnSync(
                    'bash',
                    [
                        '-c',
                        PH_SCRIPT.replaceAll('/posthog/.ph', directory).replace(
                            '/tmp/posthog-ph.lock',
                            join(directory, 'lock')
                        ),
                        'ph',
                        'help',
                    ],
                    { encoding: 'utf8' }
                )
                expect(command.status).toBe(0)
                expect(command.stderr).toBe('Warning: Some insights are excluded.\n')
                expect(format === 'json' ? JSON.parse(command.stdout) : command.stdout.trimEnd()).toEqual(result)
            } finally {
                rmSync(directory, { recursive: true, force: true })
            }
        }
    )

    it.each(['hogql', 'run'])('cancels %s from the response open and accepts the next command', async (name) => {
        const filesystem = new TerminalFilesystem()
        let querySignal: AbortSignal | undefined
        new TerminalCommands(filesystem, async ([command], _cwd, { signal }) => {
            if (command === name) {
                querySignal = signal
                await new Promise<void>((_resolve, reject) =>
                    signal!.addEventListener('abort', () => reject(new Error('Query cancelled')), { once: true })
                )
            }
            return 'Next command completed'
        })
        const bridge = filesystem.root.children!.get('.ph')!.children!
        const write = async (argv: string[]): Promise<void> =>
            (await bridge.get('request')!.open!()).save!(
                new TextEncoder().encode(JSON.stringify({ argv, cwd: '/tmp' }))
            )
        await write([name])
        const controller = new AbortController()
        const response = bridge.get('response')!.open!(controller.signal)
        controller.abort()
        expect(querySignal?.aborted).toBe(true)
        expect(JSON.parse(new TextDecoder().decode((await response).bytes))).toEqual({
            ok: false,
            error: 'Query cancelled',
        })
        await write(['help'])
        expect(JSON.parse(new TextDecoder().decode((await bridge.get('response')!.open!()).bytes))).toEqual({
            ok: true,
            result: 'Next command completed',
        })
    })
})
