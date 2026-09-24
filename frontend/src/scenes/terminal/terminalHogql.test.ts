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

    it.each(['argument', 'stdin'])('preserves SQL quotes, newlines, and shell metacharacters from %s', (source) => {
        const query = "select 'a\\b', '@file', '$(echo untouched)'\n-- another line"
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

    it('returns query failures on stderr with a nonzero exit status', () => {
        writeFileSync(join(directory, 'ph'), '#!/bin/sh\ncat >/dev/null\necho "Query failed" >&2\nexit 1\n')
        const result = run(['select missing'])
        expect(result.status).toBe(1)
        expect(result.stdout).toBe('')
        expect(result.stderr).toBe('Query failed\n')
    })
})
