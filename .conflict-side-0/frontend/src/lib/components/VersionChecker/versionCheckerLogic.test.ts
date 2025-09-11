import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { PosthogJSDeprecation, versionCheckerLogic } from './versionCheckerLogic'

const useMockedVersions = (
    githubVersions: { version: string }[],
    usedVersions: { version: string; timestamp: string }[],
    deprecateBeforeVersion: string
): void => {
    useMocks({
        get: {
            'https://api.github.com/repos/posthog/posthog-js/tags': () => [
                200,
                githubVersions.map((x) => ({ name: x.version })),
            ],
            'https://raw.githubusercontent.com/PostHog/posthog-js/main/deprecation.json': () => [
                200,
                {
                    deprecateBeforeVersion,
                } as PosthogJSDeprecation,
            ],
        },
        post: {
            '/api/environments/:team_id/query': () => [
                200,
                {
                    results: usedVersions.map((x) => [x.version, x.timestamp]),
                },
            ],
        },
    })
}

describe('versionCheckerLogic', () => {
    // jest.setTimeout(1000)
    let logic: ReturnType<typeof versionCheckerLogic.build>

    beforeEach(() => {
        useMockedVersions([{ version: '1.0.0' }], [{ version: '1.0.0', timestamp: '2023-01-01T12:00:00Z' }], '1.0.0')
        initKeaTests()
        localStorage.clear()
        logic = versionCheckerLogic()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('should load and check versions', async () => {
        logic.mount()
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                availableVersions: {
                    sdkVersions: [{ major: 1, minor: 0, patch: 0 }],
                    deprecation: { deprecateBeforeVersion: '1.0.0' },
                },
                usedVersions: [
                    {
                        version: { major: 1, minor: 0, patch: 0 },
                        timestamp: '2023-01-01T12:00:00Z',
                    },
                ],
                lastCheckTimestamp: expect.any(Number),
                versionWarning: null,
            })
    })

    it.each([
        { versionCount: 1, expectation: null },
        {
            versionCount: 11,
            expectation: null,
        },
        {
            versionCount: 51,
            expectation: {
                latestUsedVersion: '1.0.0',
                latestAvailableVersion: '1.0.50',
                numVersionsBehind: 50,
                level: 'error',
            },
        },
        {
            minorUsedVersion: 40,
            versionCount: 1,
            expectation: {
                latestUsedVersion: '1.0.0',
                latestAvailableVersion: '1.40.0',
                numVersionsBehind: 40,
                level: 'warning',
            },
        },
        {
            majorUsedVersion: 2,
            versionCount: 1,
            expectation: {
                latestUsedVersion: '1.0.0',
                latestAvailableVersion: '2.0.0',
                numVersionsBehind: 1,
                level: 'info',
            },
        },
    ])('return a version warning if diff is great enough', async (options) => {
        // TODO: How do we clear the persisted value?
        const versionsList = Array.from({ length: options.versionCount }, (_, i) => ({
            version: `${options.majorUsedVersion || 1}.${options.minorUsedVersion || 0}.${i}`,
        })).reverse()

        useMockedVersions(
            versionsList,
            [
                {
                    version: '1.0.0',
                    timestamp: '2023-01-01T12:00:00Z',
                },
            ],
            '1.0.0'
        )

        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expectLogic(logic).toMatchValues({ versionWarning: options.expectation })
    })

    it.each([
        {
            usedVersions: [
                { version: '1.9.0', timestamp: '2023-01-01T12:00:00Z' },
                { version: '1.83.1', timestamp: '2023-01-01T10:00:00Z' },
            ],
            expectation: null,
        },
        {
            usedVersions: [
                { version: '1.80.0', timestamp: '2023-01-01T12:00:00Z' },
                { version: '1.83.1', timestamp: '2023-01-01T10:00:00Z' },
                { version: '1.20.1', timestamp: '2023-01-01T10:00:00Z' },
                { version: '1.0.890', timestamp: '2023-01-01T10:00:00Z' },
                { version: '0.89.5', timestamp: '2023-01-01T10:00:00Z' },
                { version: '0.0.5', timestamp: '2023-01-01T10:00:00Z' },
                { version: '1.84.0', timestamp: '2023-01-01T08:00:00Z' },
            ],
            expectation: null,
        },
        {
            usedVersions: [
                { version: '1.40.0', timestamp: '2023-01-01T12:00:00Z' },
                { version: '1.41.1-beta', timestamp: '2023-01-01T10:00:00Z' },
                { version: '1.42.0', timestamp: '2023-01-01T08:00:00Z' },
                { version: '1.42.0-delta', timestamp: '2023-01-01T08:00:00Z' },
            ],
            expectation: {
                latestUsedVersion: '1.42.0',
                numVersionsBehind: 42,
                latestAvailableVersion: '1.84.0',
                level: 'warning',
            },
        },
    ])('when having multiple versions used, should match with the latest one', async (options) => {
        useMockedVersions([{ version: '1.84.0' }], options.usedVersions, '1.0.0')

        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expectLogic(logic).toMatchValues({ versionWarning: options.expectation })
    })

    it('should show an error if the current version is below the deprecation version', async () => {
        useMockedVersions(
            [{ version: '1.0.1' }, { version: '1.0.0' }],
            [{ version: '1.0.0', timestamp: '2023-01-01T12:00:00Z' }],
            '1.0.1'
        )

        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expectLogic(logic).toMatchValues({
            versionWarning: {
                latestUsedVersion: '1.0.0',
                latestAvailableVersion: '1.0.1',
                level: 'error',
            },
        })
    })
})
