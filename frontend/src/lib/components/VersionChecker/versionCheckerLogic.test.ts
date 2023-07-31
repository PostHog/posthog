import { useMocks } from '~/mocks/jest'
import { SDKVersion, versionCheckerLogic } from './versionCheckerLogic'
import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'

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
    jest.setTimeout(1000)
    let logic: ReturnType<typeof versionCheckerLogic.build>

    beforeEach(() => {
        useMockedVersions([{ version: '1.0.0' }], [{ version: '1.0.0', timestamp: '2023-01-01T12:00:00Z' }])
        initKeaTests()
        logic = versionCheckerLogic()
        logic.mount()
    })

    it('should load and check versions', async () => {
        await expectLogic(logic)
            .toDispatchActions(['loadAvailableVersions', 'loadUsedVersions'])
            .toDispatchActions(['loadAvailableVersionsSuccess', 'loadUsedVersionsSuccess'])
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

    it('return a version warning if diff is great enough', async () => {
        // TODO: How do we clear the persisted value?
        const versionsList = Array.from({ length: 10 }, (_, i) => ({
            version: `1.0.${i}`,
        })).reverse()

        useMockedVersions(versionsList, [
            {
                version: '1.0.0',
                timestamp: '2023-01-01T12:00:00Z',
            },
        ])

        await expectLogic(logic).toDispatchActions(['loadAvailableVersionsSuccess', 'loadUsedVersionsSuccess'])

        expectLogic(logic).toMatchValues({
            versionWarning: {},
        })
    })
})
