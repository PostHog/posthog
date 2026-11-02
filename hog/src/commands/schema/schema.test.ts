import { describe, expect, test } from 'bun:test'

import { runHog, TEST_CREDENTIALS } from '@/testing'

const AGENT = { ...TEST_CREDENTIALS, CLAUDECODE: '1' }

const definitions = (content: string) => (url: string) =>
    url.endsWith('/event_definitions/typescript/')
        ? { status: 200, body: { content, event_count: 3, schema_hash: 'hash-new' } }
        : { status: 404, body: { detail: 'Not found.' } }

// The file posthog-cli 0.18 writes, plus a section hog owns.
const OLD_CONFIG = JSON.stringify({
    errorTracking: { release: { name: 'web' } },
    languages: {
        typescript: {
            output_path: 'src/lib/posthog-typed.ts',
            schema_hash: 'hash-old',
            updated_at: '2026-01-01T00:00:00+00:00',
            event_count: 2,
        },
    },
})

describe('hog schema', () => {
    test('pull regenerates the languages a posthog-cli posthog.json lists and keeps the rest of the file', async () => {
        const result = await runHog(['schema', 'pull'], {
            env: AGENT,
            cwd: '/work/app',
            files: { '/work/posthog.json': OLD_CONFIG, '/work/src/lib/posthog-typed.ts': 'old' },
            respond: definitions('new'),
        })
        expect(result.exitCode).toBe(0)
        expect(result.files['/work/src/lib/posthog-typed.ts']).toBe('new')
        expect(JSON.parse(result.files['/work/posthog.json']!)).toEqual({
            errorTracking: { release: { name: 'web' } },
            languages: {
                typescript: {
                    output_path: 'src/lib/posthog-typed.ts',
                    schema_hash: 'hash-new',
                    updated_at: '2026-01-01T00:00:00.000Z',
                    event_count: 3,
                },
            },
        })
    })

    test('pull leaves an up-to-date module and posthog.json alone', async () => {
        const config = JSON.stringify({
            languages: { typescript: { output_path: 'out.ts', schema_hash: 'hash-new', event_count: 3 } },
        })
        const result = await runHog(['schema', 'pull'], {
            env: AGENT,
            files: { '/work/posthog.json': config, '/work/out.ts': 'same' },
            respond: definitions('same'),
        })
        expect(result.stdout).toContain('"status":"unchanged"')
        expect(result.files['/work/posthog.json']).toBe(config)
    })

    test.each([
        ['a folder gets the default file name', 'src/', '/work/src/posthog-typed.ts', 'src/posthog-typed.ts'],
        ['a sibling folder stays relative', '../web/typed.ts', '/web/typed.ts', '../web/typed.ts'],
    ])('pull into %s and starts a posthog.json', async (_name, file, written, stored) => {
        const result = await runHog(['schema', 'pull', '--language', 'typescript', '--file', file], {
            env: AGENT,
            respond: definitions('generated'),
        })

        expect(result.files[written]).toBe('generated')
        expect(JSON.parse(result.files['/work/posthog.json']!)).toMatchObject({
            $schema: expect.stringContaining('posthog.schema.json'),
            languages: { typescript: { output_path: stored } },
        })
    })

    test('pull asks an agent for --language instead of prompting', async () => {
        const result = await runHog(['schema', 'pull'], { env: AGENT })
        expect(result.exitCode).toBe(2)
        expect(result.error().code).toBe('language_required')
        expect(result.requests).toEqual([])
    })

    test.each([
        ['the events have not changed', 'hash-new', { '/work/out.ts': '' }, 'up_to_date', 0],
        ['the events changed', 'hash-old', { '/work/out.ts': '' }, 'outdated', 1],
        ['the module is gone', 'hash-new', {}, 'missing', 1],
    ])('status when %s', async (_name, hash, files, status, exitCode) => {
        const config = JSON.stringify({ languages: { typescript: { output_path: 'out.ts', schema_hash: hash } } })
        const result = await runHog(['schema', 'status'], {
            env: AGENT,
            files: { '/work/posthog.json': config, ...files },
            respond: definitions(''),
        })
        expect(result.exitCode).toBe(exitCode)
        expect(result.json()).toMatchObject({ language: 'typescript', file: 'out.ts', status })
    })
})
