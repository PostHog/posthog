import { describe, expect, test } from 'bun:test'
import { dirname } from 'node:path'

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

// As in PostHog, only the 2.x module adds its SDK to the schema hash.
const goDefinitions = (url: string): { status: number; body: object } => {
    const query = url.split('/event_definitions/golang/')[1]
    const v2 = query === '?sdk=posthog-go-v2'
    return query === undefined
        ? { status: 404, body: { detail: 'Not found.' } }
        : {
              status: 200,
              body: {
                  content: `go module ${query}`,
                  event_count: 1,
                  schema_hash: v2 ? 'hash-go-v2' : 'hash-go',
                  sdk: v2 ? 'posthog-go-v2' : 'posthog-go',
              },
          }
}

const GO_MOD_V1 = 'module example.com/app\n\ngo 1.22\n\nrequire github.com/posthog/posthog-go v1.12.5\n'
const GO_MOD_V2 =
    'module example.com/app\n\ngo 1.22\n\nrequire (\n\tgithub.com/google/uuid v1.6.0\n\tgithub.com/posthog/posthog-go/v2 v2.1.1 // indirect\n)\n'
const GO_MOD_BOTH = GO_MOD_V1 + 'require github.com/posthog/posthog-go/v2 v2.1.1\n'
const GO_MOD_REPLACE_ONLY =
    'module example.com/app\n\ngo 1.22\n\nreplace (\n\tgithub.com/posthog/posthog-go/v2 v2.1.1 => ../posthog-go\n)\n'

const goRequests = (result: { requests: { url: string }[] }): (string | undefined)[] =>
    result.requests.map((request) => request.url.split('/event_definitions/')[1])

const recordedGoSdk = (result: { files: Record<string, string> }): string | undefined =>
    (readJson(result.files['/work/posthog.json']!) as { languages: { golang: { sdk?: string } } }).languages.golang.sdk

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
    test.each([
        ['as posthog-cli wrote it', OLD_CONFIG, 2, ''],
        ['indented with 4 spaces', `${JSON.stringify(readJson(OLD_CONFIG), null, 4)}\n`, 4, '\n'],
        ['indented with tabs', JSON.stringify(readJson(OLD_CONFIG), null, '\t'), '\t', ''],
    ])(
        'pull regenerates the languages a posthog-cli posthog.json lists and keeps the rest of the file, %s',
        async (_name, config, indent, newline) => {
            const result = await runHog(['schema', 'pull'], {
                env: AGENT,
                cwd: '/work/app',
                files: { '/work/posthog.json': config, '/work/src/lib/posthog-typed.ts': 'old' },
                respond: definitions('new'),
            })

            expect(result.exitCode).toBe(EXIT_SUCCESS)
            expect(result.files['/work/src/lib/posthog-typed.ts']).toBe('new')
            const expected = {
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
            }
            expect(result.files['/work/posthog.json']).toBe(`${JSON.stringify(expected, null, indent)}${newline}`)
        }
    )

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

    test.each([
        ['an absolute path', '/home/ana/.bashrc', '/home/ana/.bashrc', {}],
        ['a path that climbs out of the project', '../outside/typed.ts', '/outside/typed.ts', {}],
        [
            'a file that links out of the project',
            'typed.ts',
            '/home/ana/.bashrc',
            { '/work/typed.ts': '/home/ana/.bashrc' },
        ],
    ])('pull refuses an output_path in posthog.json that is %s', async (_name, outputPath, outside, links) => {
        const config = JSON.stringify({
            languages: { typescript: { output_path: outputPath, schema_hash: 'hash-old' } },
        })

        const result = await runHog(['schema', 'pull'], {
            env: AGENT,
            files: { '/work/posthog.json': config, [outside]: 'keep' },
            links,
            respond: definitions('generated'),
        })

        expect(result.exitCode).toBe(EXIT_FAILURE)
        expect(result.error()).toMatchObject({ code: 'unsafe_output_path' })
        expect(result.files[outside]).toBe('keep')
        expect(result.files['/work/posthog.json']).toBe(config)
    })

    test.each([
        ['the default path', [], '/work/posthog-typed.ts', '/work'],
        ['a --file folder', ['--file', 'src/'], '/work/src/posthog-typed.ts', '/work'],
        ['a --file path', ['--file', 'src/typed.ts'], '/work/src/typed.ts', '/work'],
        ['a --file path above the working folder', ['--file', '../gen/typed.ts'], '/work/gen/typed.ts', '/work/app'],
    ])(
        'pull refuses a module file inside the repository that links out of it, at %s',
        async (_name, args, planted, cwd) => {
            const result = await runHog(['schema', 'pull', '--language', 'typescript', ...args], {
                env: AGENT,
                cwd,
                files: {
                    '/work/.git/HEAD': '',
                    [`${cwd}/README.md`]: '',
                    [`${dirname(planted)}/README.md`]: '',
                    '/home/ana/.bashrc': 'keep',
                },
                links: { [planted]: '/home/ana/.bashrc' },
                respond: definitions('generated'),
            })

            expect(result.exitCode).toBe(EXIT_FAILURE)
            expect(result.error()).toMatchObject({ code: 'unsafe_output_path' })
            expect(result.files['/home/ana/.bashrc']).toBe('keep')
            expect(result.files[`${cwd}/posthog.json`]).toBeUndefined()
        }
    )

    test('pull refuses to write a posthog.json that links out of its folder', async () => {
        const result = await runHog(['schema', 'pull', '--language', 'typescript'], {
            env: AGENT,
            files: { '/work/README.md': '' },
            links: { '/work/posthog.json': '/home/ana/.bashrc' },
            respond: definitions('generated'),
        })

        expect(result.exitCode).toBe(EXIT_FAILURE)
        expect(result.error()).toMatchObject({ code: 'unsafe_config_path' })
        expect(result.files['/home/ana/.bashrc']).toBeUndefined()
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
        ['no go.mod', [], undefined, '', [], undefined],
        ['a go.mod that requires posthog-go 2.x', [], GO_MOD_V2, '?sdk=posthog-go-v2', [], undefined],
        ['a go.mod that requires posthog-go 1.x', [], GO_MOD_V1, '', [], undefined],
        ['a go.mod that requires both majors', [], GO_MOD_BOTH, '', [], undefined],
        ['a go.mod that only replaces posthog-go', [], GO_MOD_REPLACE_ONLY, '', [], undefined],
        [
            '--sdk posthog-go-v2 over a 1.x go.mod',
            ['--sdk', 'posthog-go-v2'],
            GO_MOD_V1,
            '?sdk=posthog-go-v2',
            [],
            'posthog-go-v2',
        ],
        ['--sdk posthog-go over a 2.x go.mod', ['--sdk', 'posthog-go'], GO_MOD_V2, '', [], 'posthog-go'],
        [
            'a person with no go.mod who picks 2.x',
            [],
            undefined,
            '?sdk=posthog-go-v2',
            ['posthog-go-v2', ''],
            'posthog-go-v2',
        ],
        ['a person with no go.mod who picks 1.x', [], undefined, '', ['posthog-go', ''], 'posthog-go'],
        ['a person with a 2.x go.mod, who is not asked', [], GO_MOD_V2, '?sdk=posthog-go-v2', [''], undefined],
    ])(
        'pull for a new Go module with %s asks PostHog for the right module',
        async (_name, flags, goMod, query, answers, recorded) => {
            const person = answers.length > 0
            const result = await runHog(['schema', 'pull', '--language', 'golang', ...flags], {
                env: person ? TEST_CREDENTIALS : AGENT,
                stdoutIsTTY: person,
                answers,
                files: goMod ? { '/work/go.mod': goMod } : {},
                respond: goDefinitions,
            })

            expect(result.exitCode).toBe(EXIT_SUCCESS)
            expect(goRequests(result)).toEqual([`golang/${query}`])
            expect(result.files['/work/posthog-typed.go']).toBe(`go module ${query}`)
            expect(recordedGoSdk(result)).toBe(recorded)
        }
    )

    test.each([
        [
            'the go.mod next to the module wins over the one above it',
            {},
            [],
            GO_MOD_V2,
            '?sdk=posthog-go-v2',
            undefined,
        ],
        [
            'posthog.json sets 2.x over a 1.x go.mod',
            { sdk: 'posthog-go-v2' },
            [],
            GO_MOD_V1,
            '?sdk=posthog-go-v2',
            'posthog-go-v2',
        ],
        ['posthog.json sets 1.x over a 2.x go.mod', { sdk: 'posthog-go' }, [], GO_MOD_V2, '', 'posthog-go'],
        [
            '--sdk replaces what posthog.json sets',
            { sdk: 'posthog-go-v2' },
            ['--sdk', 'posthog-go'],
            GO_MOD_V2,
            '',
            'posthog-go',
        ],
        [
            'posthog.json sets a TypeScript SDK, which the go.mod overrides',
            { sdk: 'none' },
            [],
            GO_MOD_V2,
            '?sdk=posthog-go-v2',
            undefined,
        ],
    ])('pull for a saved Go module: %s', async (_name, sdk, flags, nearestGoMod, query, recorded) => {
        const config = { languages: { golang: { output_path: 'svc/typed.go', schema_hash: 'hash-old', ...sdk } } }
        const result = await runHog(['schema', 'pull', '--language', 'golang', ...flags], {
            env: TEST_CREDENTIALS,
            stdoutIsTTY: true,
            files: {
                '/work/posthog.json': JSON.stringify(config),
                '/work/go.mod': GO_MOD_V1,
                '/work/svc/go.mod': nearestGoMod,
                '/work/svc/typed.go': 'old',
            },
            respond: goDefinitions,
        })

        expect(result.exitCode).toBe(EXIT_SUCCESS)
        expect(goRequests(result)).toEqual([`golang/${query}`])
        expect(result.files['/work/svc/typed.go']).toBe(`go module ${query}`)
        expect(recordedGoSdk(result)).toBe(recorded)
    })

    test('pull for Go does not ask a person about a module saved before the SDK choice existed', async () => {
        const config = { languages: { golang: { output_path: 'typed.go', schema_hash: 'hash-old' } } }
        const result = await runHog(['schema', 'pull', '--language', 'golang'], {
            env: TEST_CREDENTIALS,
            stdoutIsTTY: true,
            files: { '/work/posthog.json': JSON.stringify(config), '/work/typed.go': 'old' },
            respond: goDefinitions,
        })

        expect(result.exitCode).toBe(EXIT_SUCCESS)
        expect(goRequests(result)).toEqual(['golang/'])
    })

    test.each([
        ['keeps a 2.x module when go.mod and the events are the same', {}, [], GO_MOD_V2, 'old', undefined],
        ['rewrites a 2.x module when go.mod moves to 1.x', {}, [], GO_MOD_V1, 'go module ', undefined],
        [
            'keeps a 2.x module that posthog.json sets when go.mod requires 1.x',
            { sdk: 'posthog-go-v2' },
            [],
            GO_MOD_V1,
            'old',
            'posthog-go-v2',
        ],
        [
            'records --sdk for a 2.x module that go.mod already chose',
            {},
            ['--sdk', 'posthog-go-v2'],
            GO_MOD_V2,
            'go module ?sdk=posthog-go-v2',
            'posthog-go-v2',
        ],
    ])('pull for Go %s', async (_name, sdk, flags, goMod, content, recorded) => {
        const config = JSON.stringify({
            languages: { golang: { output_path: 'typed.go', schema_hash: 'hash-go-v2', ...sdk } },
        })
        const result = await runHog(['schema', 'pull', '--language', 'golang', ...flags], {
            env: AGENT,
            files: { '/work/posthog.json': config, '/work/go.mod': goMod, '/work/typed.go': 'old' },
            respond: goDefinitions,
        })

        expect(result.exitCode).toBe(EXIT_SUCCESS)
        expect(result.files['/work/typed.go']).toBe(content)
        if (content === 'old') {
            expect(result.files['/work/posthog.json']).toBe(config)
        } else {
            expect(recordedGoSdk(result)).toBe(recorded)
        }
    })

    test.each([
        [
            'a 2.x module is up to date when go.mod requires 2.x',
            {},
            GO_MOD_V2,
            '?sdk=posthog-go-v2',
            'up_to_date',
            EXIT_SUCCESS,
        ],
        ['a 2.x module is outdated when go.mod requires 1.x', {}, GO_MOD_V1, '', 'outdated', EXIT_FAILURE],
        [
            'a 2.x module that posthog.json sets is up to date when go.mod requires 1.x',
            { sdk: 'posthog-go-v2' },
            GO_MOD_V1,
            '?sdk=posthog-go-v2',
            'up_to_date',
            EXIT_SUCCESS,
        ],
    ])('status for Go: %s', async (_name, sdk, goMod, query, status, exitCode) => {
        const config = JSON.stringify({
            languages: { golang: { output_path: 'typed.go', schema_hash: 'hash-go-v2', ...sdk } },
        })
        const result = await runHog(['schema', 'status'], {
            env: AGENT,
            files: { '/work/posthog.json': config, '/work/go.mod': goMod, '/work/typed.go': 'old' },
            respond: goDefinitions,
        })

        expect(result.exitCode).toBe(exitCode)
        expect(goRequests(result)).toEqual([`golang/${query}`])
        expect(result.json()).toMatchObject({ language: 'golang', status })
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
