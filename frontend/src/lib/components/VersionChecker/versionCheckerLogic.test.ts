import { expectLogic } from 'kea-test-utils'
import { rest } from 'msw'

import { compareVersion } from 'lib/utils/semver'

import { mswServer } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { versionCheckerLogic } from './versionCheckerLogic'

// Helper to generate dates relative to now
const daysAgo = (days: number): string => {
    const date = new Date()
    date.setDate(date.getDate() - days)
    return date.toISOString()
}

// Helper to build the mock response data for SDK doctor API
const buildSdkDoctorResponse = (
    latestVersion: string,
    usedVersions: { version: string; count: number; releaseDate?: string }[]
): { web: { latest_version: string; usage: object[] } } => {
    // Sort by semver descending to match backend behavior (see products/growth/dags/team_sdk_versions.py:43)
    const sortedVersions = [...usedVersions].sort((a, b) => compareVersion(b.version, a.version))

    return {
        web: {
            latest_version: latestVersion,
            usage: sortedVersions.map((v) => ({
                lib_version: v.version,
                count: v.count,
                is_latest: v.version === latestVersion,
                max_timestamp: '2023-01-01T12:00:00Z',
                // Default to 60 days ago to pass the 30-day single version grace period
                release_date: v.releaseDate ?? daysAgo(60),
            })),
        },
    }
}

describe('versionCheckerLogic', () => {
    let logic: ReturnType<typeof versionCheckerLogic.build>

    afterEach(() => {
        logic?.unmount()
    })

    const setupTest = (
        latestVersion: string,
        usedVersions: { version: string; count: number; releaseDate?: string }[]
    ): void => {
        const mockResponse = buildSdkDoctorResponse(latestVersion, usedVersions)
        mswServer.use(rest.get('/api/sdk_doctor', (_req, res, ctx) => res(ctx.json(mockResponse))))
        initKeaTests()
        localStorage.clear()
        logic = versionCheckerLogic({ teamId: 1 })
    }

    it('should not show warning when on latest version', async () => {
        setupTest('1.0.0', [{ version: '1.0.0', count: 100 }])
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
        setupTest(options.latestVersion, [{ version: options.usedVersion, count: 100 }])

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
        setupTest(options.latestVersion, options.usedVersions)

        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expectLogic(logic).toMatchValues({ versionWarning: options.expectation })
    })

    it('should show Current badge when used version is newer than latest cached from GitHub', async () => {
        // Simulate stale cache: GitHub says latest is 1.300.0 but user has 1.333.0
        setupTest('1.300.0', [{ version: '1.333.0', count: 100 }])
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        const augmented = logic.values.augmentedData
        expect(augmented?.web?.allReleases[0]?.isCurrentOrNewer).toBe(true)
    })
})
