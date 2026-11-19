import { describe, expect, test } from 'bun:test'

import { EXIT_FAILURE, EXIT_SUCCESS, EXIT_USAGE } from '@/core/errors'
import { readJson, runHog, TEST_CREDENTIALS } from '@/testing'

const AGENT = { ...TEST_CREDENTIALS, CLAUDECODE: '1' }

// PostHog hashes the types-only module differently, because its generator has its own version.
const definitions = (content: string) => (url: string) =>
    url.endsWith('/event_definitions/typescript/')
        ? { status: 200, body: { content, event_count: 3, schema_hash: 'hash-new' } }
        : url.endsWith('/event_definitions/typescript/?sdk=none')
          ? { status: 200, body: { content, event_count: 3, schema_hash: 'hash-types', sdk: 'none' } }
          : { status: 404, body: { detail: 'Not found.' } }

// Both Go modules share a schema hash here, so only the SDK tells hog that the module has to change.
const goDefinitions = (url: string): { status: number; body: object } => {
    const query = url.split('/event_definitions/golang/')[1]
    return query === undefined
        ? { status: 404, body: { detail: 'Not found.' } }
        : {
              status: 200,
              body: {
                  content: `go module ${query}`,
                  event_count: 1,
                  schema_hash: 'hash-go',
                  sdk: query === '?sdk=posthog-go-v2' ? 'posthog-go-v2' : 'posthog-go',
              },
          }
}

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
        expect(result.exitCode).toBe(EXIT_SUCCESS)
        expect(result.files['/work/src/lib/posthog-typed.ts']).toBe('new')
        expect(readJson(result.files['/work/posthog.json']!)).toEqual({
            errorTracking: { release: { name: 'web' } },
            languages: {
                typescript: {
                    output_path: 'src/lib/posthog-typed.ts',
                    sdk: 'posthog-js',
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
        expect(readJson(result.files['/work/posthog.json']!)).toMatchObject({
            $schema: expect.stringContaining('posthog.schema.json'),
            languages: { typescript: { output_path: stored } },
        })
    })

    test('pull asks an agent for --language instead of prompting', async () => {
        const result = await runHog(['schema', 'pull'], { env: AGENT })
        expect(result.exitCode).toBe(EXIT_USAGE)
        expect(result.error().code).toBe('language_required')
        expect(result.requests).toEqual([])
    })

    test.each([
        ['golang', 'none'],
        ['typescript', 'posthog-go-v2'],
        ['python', 'posthog-go'],
    ])('pull --language %s rejects --sdk %s, which belongs to another language', async (language, sdk) => {
        const result = await runHog(['schema', 'pull', '--language', language, '--sdk', sdk], { env: AGENT })
        expect(result.exitCode).toBe(EXIT_USAGE)
        expect(result.error().code).toBe('usage_error')
        expect(result.requests).toEqual([])
    })

    test.each([
        ['no --sdk and nothing saved', [], undefined, '', undefined],
        ['--sdk posthog-go', ['--sdk', 'posthog-go'], undefined, '', 'posthog-go'],
        ['--sdk posthog-go-v2', ['--sdk', 'posthog-go-v2'], undefined, '?sdk=posthog-go-v2', 'posthog-go-v2'],
        ['a saved posthog-go-v2 entry', [], 'posthog-go-v2', '?sdk=posthog-go-v2', 'posthog-go-v2'],
        [
            '--sdk posthog-go over a saved posthog-go-v2 entry',
            ['--sdk', 'posthog-go'],
            'posthog-go-v2',
            '',
            'posthog-go',
        ],
    ])('pull for Go with %s asks PostHog for the right module', async (_name, flags, saved, query, stored) => {
        const config = { languages: { golang: { output_path: 'typed.go', schema_hash: 'hash-old', sdk: saved } } }
        const result = await runHog(['schema', 'pull', '--language', 'golang', ...flags], {
            env: AGENT,
            files: saved ? { '/work/posthog.json': JSON.stringify(config), '/work/typed.go': 'old' } : {},
            respond: goDefinitions,
        })

        expect(result.exitCode).toBe(EXIT_SUCCESS)
        expect(result.requests.map((request) => request.url.split('/event_definitions/')[1])).toEqual([
            `golang/${query}`,
        ])
        const file = saved ? '/work/typed.go' : '/work/posthog-typed.go'
        expect(result.files[file]).toBe(`go module ${query}`)
        const written = readJson(result.files['/work/posthog.json']!) as { languages: { golang: { sdk?: string } } }
        expect(written.languages.golang.sdk).toBe(stored)
    })

    test.each([
        ['keeps the module when the SDK and the events are the same', [], 'old'],
        ['rewrites the module when only the SDK changed', ['--sdk', 'posthog-go'], 'go module '],
    ])('pull for Go %s', async (_name, flags, content) => {
        const config = {
            languages: { golang: { output_path: 'typed.go', schema_hash: 'hash-go', sdk: 'posthog-go-v2' } },
        }
        const result = await runHog(['schema', 'pull', '--language', 'golang', ...flags], {
            env: AGENT,
            files: { '/work/posthog.json': JSON.stringify(config), '/work/typed.go': 'old' },
            respond: goDefinitions,
        })

        expect(result.exitCode).toBe(EXIT_SUCCESS)
        expect(result.files['/work/typed.go']).toBe(content)
    })

    test('pull for Go fails on a PostHog that ignores --sdk posthog-go-v2, and writes nothing', async () => {
        const result = await runHog(['schema', 'pull', '--language', 'golang', '--sdk', 'posthog-go-v2'], {
            env: AGENT,
            respond: () => ({
                status: 200,
                body: { content: 'go 1.x module', event_count: 1, schema_hash: 'hash-go' },
            }),
        })

        expect(result.exitCode).toBe(EXIT_FAILURE)
        expect(result.error().code).toBe('sdk_unsupported')
        expect(result.files).toEqual({})
    })

    test.each([
        ['the events have not changed', 'hash-new', {}, { '/work/out.ts': '' }, 'up_to_date', EXIT_SUCCESS],
        [
            'types-only events have not changed',
            'hash-types',
            { sdk: 'none' },
            { '/work/out.ts': '' },
            'up_to_date',
            EXIT_SUCCESS,
        ],
        ['the events changed', 'hash-old', {}, { '/work/out.ts': '' }, 'outdated', EXIT_FAILURE],
        ['the module is gone', 'hash-new', {}, {}, 'missing', EXIT_FAILURE],
    ])('status when %s', async (_name, hash, sdk, files, status, exitCode) => {
        const config = JSON.stringify({
            languages: { typescript: { output_path: 'out.ts', schema_hash: hash, ...sdk } },
        })
        const result = await runHog(['schema', 'status'], {
            env: AGENT,
            files: { '/work/posthog.json': config, ...files },
            respond: definitions(''),
        })
        expect(result.exitCode).toBe(exitCode)
        expect(result.json()).toMatchObject({ language: 'typescript', file: 'out.ts', status })
    })
})
