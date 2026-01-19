import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { versionCheckerLogic } from './versionCheckerLogic'

const useMockedSdkDoctor = (
    latestVersion: string,
    usedVersions: { version: string; count: number; releaseDate?: string }[]
): void => {
    useMocks({
        get: {
            'api/sdk_doctor/': () => [
                200,
                {
                    web: {
                        latest_version: latestVersion,
                        usage: usedVersions.map((v) => ({
                            lib_version: v.version,
                            count: v.count,
                            is_latest: v.version === latestVersion,
                            max_timestamp: '2023-01-01T12:00:00Z',
                            release_date: v.releaseDate ?? '2023-01-01T00:00:00Z',
                        })),
                    },
                },
            ],
        },
    })
}

describe('versionCheckerLogic', () => {
    let logic: ReturnType<typeof versionCheckerLogic.build>

    beforeEach(() => {
        useMockedSdkDoctor('1.0.0', [{ version: '1.0.0', count: 100 }])
        initKeaTests()
        localStorage.clear()
        logic = versionCheckerLogic({ teamId: 1 })
    })

    afterEach(() => {
        logic.unmount()
    })

    it('should not show warning when on latest version', async () => {
        logic.mount()
        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            versionWarning: null,
        })
    })

    it.each([
        { latestVersion: '1.0.50', usedVersion: '1.0.0', expectation: null }, // Only 50 patches behind, no warning
        {
            latestVersion: '1.40.0',
            usedVersion: '1.0.0',
            expectation: {
                latestUsedVersion: '1.0.0',
                latestAvailableVersion: '1.40.0',
                level: 'error',
            },
        },
        {
            latestVersion: '1.50.0',
            usedVersion: '1.0.0',
            expectation: {
                latestUsedVersion: '1.0.0',
                latestAvailableVersion: '1.50.0',
                level: 'error',
            },
        },
        {
            latestVersion: '2.0.0',
            usedVersion: '1.0.0',
            expectation: {
                latestUsedVersion: '1.0.0',
                latestAvailableVersion: '2.0.0',
                level: 'error',
            },
        },
    ])('return a version warning if diff is great enough', async (options) => {
        useMockedSdkDoctor(options.latestVersion, [{ version: options.usedVersion, count: 100 }])

        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expectLogic(logic).toMatchValues({ versionWarning: options.expectation })
    })

    it.each([
        {
            usedVersions: [
                { version: '1.9.0', count: 50 },
                { version: '1.83.1', count: 50 },
            ],
            latestVersion: '1.84.0',
            expectation: null, // Highest used is 1.83.1, only 1 minor behind
        },
        {
            usedVersions: [
                { version: '1.40.0', count: 50 },
                { version: '1.42.0', count: 50 },
            ],
            latestVersion: '1.84.0',
            expectation: {
                latestUsedVersion: '1.42.0',
                latestAvailableVersion: '1.84.0',
                level: 'error',
            },
        },
    ])('when having multiple versions used, should match with the highest one', async (options) => {
        useMockedSdkDoctor(options.latestVersion, options.usedVersions)

        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expectLogic(logic).toMatchValues({ versionWarning: options.expectation })
    })
})
