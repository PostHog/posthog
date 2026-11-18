import { spawnSync } from 'child_process'
import { mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'

import { RM_SCRIPT } from './terminalRemove'

describe('terminal rm wrapper', () => {
    let directory: string
    let trace: string

    beforeEach(() => {
        directory = mkdtempSync(join(tmpdir(), 'terminal-rm-'))
        trace = join(directory, 'dispatch')
        writeFileSync(trace, '')
        for (const command of ['busybox', 'ph']) {
            writeFileSync(join(directory, command), '#!/bin/sh\nprintf "%s\\n" "$0" "$@" >> "$TERMINAL_RM_TRACE"\n', {
                mode: 0o700,
            })
        }
        symlinkSync('/', join(directory, 'root-link'))
    })

    afterEach(() => {
        rmSync(directory, { recursive: true, force: true })
    })

    const run = (argv: string[], cwd = '/'): ReturnType<typeof spawnSync> =>
        spawnSync('/bin/sh', ['-c', RM_SCRIPT, 'rm', ...argv], {
            cwd,
            env: { ...process.env, PATH: `${directory}:${process.env.PATH}`, TERMINAL_RM_TRACE: trace },
            encoding: 'utf8',
        })

    it.each(['/', '//', '/./', '/..', '.', '..'])('refuses root target %s before dispatching any removal', (target) => {
        const result = run(['-rf', '--', join(directory, 'local-file'), target])
        expect(result.status).toBe(1)
        expect(result.stderr).toContain('Refusing to remove the filesystem root')
        expect(readFileSync(trace, 'utf8')).toBe('')
    })

    it.each(['/posthog', '//posthog', 'posthog', '/posthog/'])(
        'refuses the mount target %s instead of dispatching to BusyBox',
        (target) => {
            const result = run(['-rf', target])
            expect(result.status).toBe(1)
            expect(result.stderr).toContain('Refusing to remove the PostHog mount')
            expect(readFileSync(trace, 'utf8')).toBe('')
        }
    )

    it('resolves a symlinked parent before checking the root', () => {
        const result = run(['-rf', `${directory}/root-link/.`])
        expect(result.status).toBe(1)
        expect(result.stderr).toContain('Refusing to remove the filesystem root')
        expect(readFileSync(trace, 'utf8')).toBe('')
    })

    it('does not fall back to BusyBox when an earlier target cannot be resolved', () => {
        const result = run(['-rf', join(directory, 'missing', 'parent', 'file'), '/'])
        expect(result.status).toBe(1)
        expect(result.stderr).toContain('Could not resolve')
        expect(readFileSync(trace, 'utf8')).toBe('')
    })

    it('still dispatches local removals with their original arguments', () => {
        const argv = ['-rf', '--', 'local-file']
        const result = run(argv, directory)
        expect(result.status).toBe(0)
        expect(result.stderr).toBe('')
        expect(readFileSync(trace, 'utf8').trim().split('\n')).toEqual([join(directory, 'busybox'), 'rm', ...argv])
    })
})
