import { describe, expect, test } from 'bun:test'

import { DEPOT_CI } from './depot-ci'

describe('Depot CI', () => {
    test.each([
        ['a Depot CI job', { GITHUB_ACTIONS: 'true', DEPOT_JOB_URL: 'https://depot.dev/orgs/x/jobs/y' }, true],
        ['a GitHub Actions job on a Depot runner', { GITHUB_ACTIONS: 'true', DEPOT_ORG_ID: 'org123' }, false],
    ])('detects %s', (_name, env, expected) => {
        expect(DEPOT_CI.detect(env)).toBe(expected)
    })
})
