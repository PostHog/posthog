import { describe, expect, test } from 'bun:test'

import { run } from '@/cli'
import { EXIT_FAILURE, EXIT_SUCCESS, EXIT_USAGE } from '@/core/errors'
import { blockStage } from '@/setup/agents-md'
import { fakeRuntime, readJson, runHog } from '@/testing'

describe('hog init', () => {
    test.each([true, false])(
        'creates a usable package and keeps project settings and repository instructions, terminal=%p',
        async (tty) => {
            const run = await runHog(tty ? ['init'] : ['init', '--stack', 'web'], {
                env: { NO_COLOR: '1' },
                stdoutIsTTY: tty,
                answers: ['web'],
                files: {
                    '/work/posthog.json': '{"host":"https://eu.posthog.com","projectId":2,"cli":{"telemetry":false}}',
                    '/work/AGENTS.md': '# Repository\n\nRun tests before pushing.\n',
                },
            })
            expect(run.exitCode).toBe(EXIT_SUCCESS)
            expect(readJson(run.files['/work/posthog.json']!)).toMatchObject({
                projectId: 2,
                cli: { telemetry: false },
                stacks: {
                    web: { dir: '.ph', environments: { production: { host: 'https://eu.posthog.com', project: 2 } } },
                },
            })
            expect(readJson(run.files['/work/.ph/package.json']!)).toMatchObject({
                dependencies: { '@posthog/sdk': expect.any(String) },
                devDependencies: { typescript: expect.any(String) },
            })
            expect(run.files['/work/.ph/tsconfig.json']).toContain('"strict": true')
            expect(run.files['/work/.ph/index.ts']).toBe('export {}\n')
            expect(run.files['/work/.ph/AGENTS.md']!.match(/^\d\./gm)).toHaveLength(7)
            expect(run.files['/work/AGENTS.md']).toContain('# Repository\n\nRun tests before pushing.')
            expect(run.files['/work/AGENTS.md']).toContain('](./.ph/AGENTS.md)')
            if (tty) {
                expect(run.stdout).toContain('Created stack web in .ph')
            } else {
                expect(run.json()).toMatchObject({ status: 'created', stack: 'web', dir: '.ph' })
            }
            expect(run.requests).toEqual([])
        }
    )

    test('an empty repository can initialize from a nested working folder', async () => {
        const run = await runHog(['init', '--stack', 'web'], {
            cwd: '/work/app',
            files: { '/work/.git/HEAD': 'ref: refs/heads/main' },
        })
        expect(run.exitCode).toBe(0)
        expect(readJson(run.files['/work/posthog.json']!)).toMatchObject({ stacks: { web: { dir: '.ph' } } })
        expect(run.files['/work/app/posthog.json']).toBeUndefined()
    })

    test('a repeat keeps the existing stack and all hand edits', async () => {
        const files = {
            '/work/posthog.json': '{"stacks":{"web":{"dir":"definitions"}}}',
            '/work/definitions/index.ts': 'hand-edited',
        }
        const run = await runHog(['init'], { files })
        expect(run.exitCode).toBe(EXIT_SUCCESS)
        expect(run.json()).toMatchObject({ status: 'existing', stack: 'web' })
        expect(run.files).toEqual(files)
    })

    test.each(['AGENTS.md', 'CLAUDE.md'])('checks broken markers in %s before changing any file', async (guide) => {
        const files = {
            '/work/AGENTS.md': '# Repository\n',
            [`/work/${guide}`]: '<!-- posthog:setup:start -->\nUnfinished\n',
            '/work/.ph/index.ts': 'export const custom = true\n',
        }
        const result = await runHog(['init', '--stack', 'web', '--yes'], { files })
        expect(result.exitCode).toBe(EXIT_FAILURE)
        expect(result.error().code).toBe('setup_block_broken')
        expect(result.files).toEqual(files)
    })

    test('previews each changed file and a stack link alone leaves product setup open', async () => {
        const files = { '/work/CLAUDE.md': '# Contributor notes\n' }
        const preview = await runHog(['init', '--stack', 'web', '--dry-run'], { files })
        const created = await runHog(['init', '--stack', 'web'], { files })
        expect(preview.exitCode).toBe(EXIT_SUCCESS)
        expect(created.exitCode).toBe(EXIT_SUCCESS)
        expect(preview.files).toEqual(files)
        const changed = [
            '.ph/package.json',
            '.ph/tsconfig.json',
            '.ph/index.ts',
            '.ph/AGENTS.md',
            'AGENTS.md',
            'CLAUDE.md',
            'posthog.json',
        ]
        expect(preview.json()).toMatchObject({ files: changed })
        expect(created.json()).toMatchObject({ files: changed })
        expect(created.files['/work/CLAUDE.md']).toContain('# Contributor notes')
        expect(await blockStage(fakeRuntime({ files: created.files }), '/work')).toBeUndefined()
    })

    test('a failure saving the configuration restores the files from before init and a retry succeeds', async () => {
        const files = {
            '/work/posthog.json': '{"projectId":7}',
            '/work/.ph/index.ts': 'export const custom = true\n',
            '/work/AGENTS.md': '# Repository\n',
            '/work/CLAUDE.md': '# Assistant notes\n',
        }
        const runtime = fakeRuntime({ files })
        const replaceFile = runtime.replaceFile
        runtime.replaceFile = (path, contents) => {
            if (path === '/work/posthog.json') {
                throw new Error('Cannot replace the file')
            }
            return replaceFile(path, contents)
        }
        const argv = ['init', '--stack', 'web', '--yes']
        expect(await run(argv, runtime)).toBe(EXIT_FAILURE)
        expect(runtime.stderr()).toContain('stack_write_failed')
        expect(runtime.files).toEqual(files)
        const retried = await runHog(argv, { files: runtime.files })
        expect(retried.exitCode).toBe(EXIT_SUCCESS)
        expect(retried.json()).toMatchObject({ status: 'created', stack: 'web' })
    })

    test.each([
        { argv: ['init'], code: EXIT_USAGE },
        { argv: ['init', '--stack', 'web'], code: EXIT_USAGE },
        { argv: ['init', '--stack', 'web', '--dry-run'], code: EXIT_SUCCESS },
        { argv: ['init', '--stack', 'web', '--dir', '../outside'], code: EXIT_USAGE },
    ])('leaves the repository intact for $argv', async ({ argv, code }) => {
        const files = { '/work/.ph/index.ts': 'hand-edited' }
        const args: string[] = [...argv]
        const run = await runHog(args, { files })
        expect(run.exitCode).toBe(code)
        expect(run.files).toEqual(files)
        if (args.includes('--dry-run')) {
            expect(run.stdout).toContain('hand-edited')
        }
    })
})
