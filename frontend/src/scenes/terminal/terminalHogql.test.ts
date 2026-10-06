import { spawnSync } from 'child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'

import { HOGQL_SCRIPT } from './terminalHogql'

describe('terminal hogql wrapper', () => {
    let directory: string

    beforeEach(() => {
        directory = mkdtempSync(join(tmpdir(), 'terminal-hogql-'))
        writeFileSync(join(directory, 'ph'), '#!/bin/sh\ncat\n', { mode: 0o700 })
    })

    afterEach(() => {
        rmSync(directory, { recursive: true, force: true })
    })

    const run = (argv: string[], input = ''): ReturnType<typeof spawnSync> =>
        spawnSync('bash', ['-c', HOGQL_SCRIPT, 'hogql', ...argv], {
            env: { ...process.env, PATH: `${directory}:${process.env.PATH}` },
            input,
            encoding: 'utf8',
        })

    it.each([
        ['argument', 0],
        ['stdin', 0],
        ['stdin', 256 * 1024],
    ])('preserves SQL quotes, newlines, and shell metacharacters from %s with %i padding bytes', (source, padding) => {
        const query = "select 'a\\b', '@file', '$(echo untouched)'\n-- another line" + 'x'.repeat(padding)
        const options = ['--connection-id', 'example-connection', '--values', '{"value":"a b"}', '--csv']
        const result = source === 'argument' ? run([...options, query]) : run(options, query)
        expect(result.status).toBe(0)
        expect(result.stderr).toBe('')
        expect(JSON.parse(String(result.stdout))).toEqual({ query, argv: options })
    })

    it('accepts SQL after -- without interpreting its leading comment as an option', () => {
        const result = run(['--json', '--', '-- comment\nselect 1'])
        expect(result.status).toBe(0)
        expect(JSON.parse(String(result.stdout))).toEqual({ query: '-- comment\nselect 1', argv: ['--json'] })
    })

    it.each([
        [['--connection-id'], 'Missing value'],
        [['--unknown'], 'Unknown option'],
        [['select', '1'], 'Quote the SQL'],
    ])('rejects invalid shell arguments %j', (argv, message) => {
        const result = run(argv)
        expect(result.status).toBe(1)
        expect(result.stdout).toBe('')
        expect(result.stderr).toContain(message)
    })

    it('keeps the interactive prompt open after a failed query until exit', () => {
        writeFileSync(join(directory, 'hogql'), HOGQL_SCRIPT)
        writeFileSync(
            join(directory, 'ph'),
            '#!/bin/sh\nrequest=$(cat)\ncase "$request" in *missing*) echo "Query failed" >&2; exit 1 ;; esac\nprintf "%s\\n" "$request"\n'
        )
        // A real PTY exercises Bash readline on both macOS and Linux.
        const driver = `
import os, pty, sys
sent = False
def read(fd: int) -> bytes:
    global sent
    if not sent:
        os.write(fd, b'select missing\\nselect 1\\nexit\\n')
        sent = True
    return os.read(fd, 65536)
sys.exit(os.waitstatus_to_exitcode(pty.spawn(['bash', sys.argv[1], '--csv'], read)))
`
        const result = spawnSync('python3', ['-c', driver, join(directory, 'hogql')], {
            env: { ...process.env, PATH: `${directory}:${process.env.PATH}` },
            input: '',
            encoding: 'utf8',
            timeout: 10000,
        })
        expect(result.stderr).toBe('')
        expect(result.status).toBe(0)
        expect(result.stdout).toContain('Query failed')
        expect(result.stdout).toContain(JSON.stringify({ query: 'select 1', argv: ['--csv'] }))
    })

    it('returns query failures on stderr with a nonzero exit status', () => {
        writeFileSync(join(directory, 'ph'), '#!/bin/sh\ncat >/dev/null\necho "Query failed" >&2\nexit 1\n')
        const result = run(['select missing'])
        expect(result.status).toBe(1)
        expect(result.stdout).toBe('')
        expect(result.stderr).toBe('Query failed\n')
    })
})
