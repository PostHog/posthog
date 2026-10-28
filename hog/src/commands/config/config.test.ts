import { describe, expect, test } from 'bun:test'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { configSchema } from '@/core/config'
import { runHog } from '@/testing'

const VALID = JSON.stringify({ errorTracking: { sources: [{ path: 'dist', kind: 'js' }] } })

describe('hog config', () => {
    test('posthog.schema.json matches the zod definitions', () => {
        const file = JSON.parse(readFileSync(join(import.meta.dir, '../../../posthog.schema.json'), 'utf8'))
        expect(file).toEqual(configSchema())
    })

    test.each([
        [
            'a valid file in the working folder',
            { '/work/posthog.json': VALID },
            0,
            { status: 'valid', path: '/work/posthog.json' },
        ],
        ['a file in a parent folder', { '/posthog.json': VALID }, 0, { status: 'valid', path: '/posthog.json' }],
        [
            'no file up to the git root',
            { '/work/.git/HEAD': 'ref: refs/heads/main', '/posthog.json': VALID },
            1,
            { status: 'missing' },
        ],
        [
            'a typo and a wrong kind',
            {
                '/work/posthog.json': JSON.stringify({
                    errorTraking: {},
                    errorTracking: { sources: [{ path: 'x', kind: 'java' }] },
                }),
            },
            1,
            {
                status: 'invalid',
                problems: [
                    expect.objectContaining({ path: 'errorTracking.sources[0].kind' }),
                    expect.objectContaining({ path: '' }),
                ],
            },
        ],
    ])('check: %s', async (_name, files, exitCode, expected) => {
        const result = await runHog(['config', 'check'], { env: { CLAUDECODE: '1' }, files })
        expect(result.exitCode).toBe(exitCode)
        expect(result.json()).toMatchObject(expected)
    })
})
