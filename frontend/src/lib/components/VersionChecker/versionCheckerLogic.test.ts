import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { SDKVersion, versionCheckerLogic } from './versionCheckerLogic'

const useMockedVersions = (githubVersions: SDKVersion[], usedVersions: SDKVersion[]): void => {
    useMocks({
        get: {
            'https://api.github.com/repos/posthog/posthog-js/tags': () => [
                200,
                githubVersions.map((x) => ({ name: x.version })),
            ],
        },
        post: {
            '/api/projects/:team/query': () => [
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
        useMockedVersions([{ version: '1.0.0' }], [{ version: '1.0.0', timestamp: '2023-01-01T12:00:00Z' }])
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
                availableVersions: [
                    {
                        version: '1.0.0',
                    },
                ],
                usedVersions: [
                    {
                        version: '1.0.0',
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
            versionCount: 10,
            expectation: {
                currentVersion: '1.0.0',
                latestVersion: '1.0.9',
                diff: 9,
                level: 'info',
            },
        },
        {
            versionCount: 15,
            expectation: {
                currentVersion: '1.0.0',
                latestVersion: '1.0.14',
                diff: 14,
                level: 'warning',
            },
        },
        {
            versionCount: 25,
            expectation: {
                currentVersion: '1.0.0',
                latestVersion: '1.0.24',
                diff: 24,
                level: 'error',
            },
        },
    ])('return a version warning if diff is great enough', async (options) => {
        // TODO: How do we clear the persisted value?
        const versionsList = Array.from({ length: options.versionCount }, (_, i) => ({
            version: `1.0.${i}`,
        })).reverse()

        useMockedVersions(versionsList, [
            {
                version: '1.0.0',
                timestamp: '2023-01-01T12:00:00Z',
            },
        ])

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
            expectation: {
                currentVersion: '1.83.1',
                latestVersion: '1.84.0',
                diff: 1,
                level: 'info',
            },
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
                { version: '1.80.0', timestamp: '2023-01-01T12:00:00Z' },
                { version: '1.83.1-beta', timestamp: '2023-01-01T10:00:00Z' },
                { version: '1.84.0-delta', timestamp: '2023-01-01T08:00:00Z' },
            ],
            expectation: { currentVersion: '1.84.0-delta', diff: 1, latestVersion: '1.84.0', level: 'info' },
        },
    ])('when having multiple versions used, should match with the latest one', async (options) => {
        useMockedVersions([{ version: '1.84.0' }], options.usedVersions)

        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expectLogic(logic).toMatchValues({ versionWarning: options.expectation })
    })
})
