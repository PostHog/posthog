import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { framesCodeSourceLogic } from './framesCodeSourceLogic'

const LINK_URL = 'https://github.com/acme/app/blob/main/src/a.ts#L1'

describe('framesCodeSourceLogic', () => {
    let logic: ReturnType<typeof framesCodeSourceLogic.build>
    let requests: { release_id: string; raw_ids: string[] }[]

    let linked: boolean

    beforeEach(() => {
        requests = []
        linked = true
        useMocks({
            post: {
                '/api/projects/:team_id/error_tracking/git-provider-file-links/resolve/': async ({ request }) => {
                    const body = (await request.json()) as { release_id: string; raw_ids: string[] }
                    requests.push(body)
                    const results =
                        linked && body.raw_ids.includes('linked/0')
                            ? [{ raw_id: 'linked/0', provider: 'github', url: LINK_URL, path: 'src/a.ts' }]
                            : []
                    return [200, { results }]
                },
            },
        })
        initKeaTests()
        logic = framesCodeSourceLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('asks for each frame once per release and remembers the frames the server did not link', async () => {
        await expectLogic(logic, () =>
            logic.actions.resolveSourceUrls({ rawIds: ['linked/0', 'unlinked/0'], releaseId: 'release-1' })
        )
            .toDispatchActions(['setSourceData'])
            .toMatchValues({
                frameSourceUrls: {
                    'release-1:linked/0': { url: LINK_URL, provider: 'github' },
                    'release-1:unlinked/0': null,
                },
            })
        expect(logic.values.getSourceDataForFrame('linked/0', 'release-1')).toEqual({
            url: LINK_URL,
            provider: 'github',
        })
        expect(logic.values.getSourceDataForFrame('linked/0', 'release-2')).toBeNull()

        await expectLogic(logic, () =>
            logic.actions.resolveSourceUrls({ rawIds: ['linked/0', 'unlinked/0', 'new/0'], releaseId: 'release-1' })
        ).toFinishListeners()

        expect(requests).toEqual([
            { release_id: 'release-1', raw_ids: ['linked/0', 'unlinked/0'] },
            { release_id: 'release-1', raw_ids: ['new/0'] },
        ])
    })

    it('sends each frame once and splits a deep stack into requests the server accepts', async () => {
        const deep = Array.from({ length: 501 }, (_, index) => `frame-${index}/0`)

        await expectLogic(logic, () =>
            logic.actions.resolveSourceUrls({ rawIds: [...deep, ...deep], releaseId: 'release-1' })
        ).toFinishListeners()

        expect(requests.map((request) => request.raw_ids.length)).toEqual([500, 1])
        expect(new Set(requests.flatMap((request) => request.raw_ids)).size).toBe(501)
    })

    it('asks again after a response that linked nothing, since the provider may have been unreachable', async () => {
        linked = false
        await expectLogic(logic, () =>
            logic.actions.resolveSourceUrls({ rawIds: ['linked/0'], releaseId: 'release-1' })
        ).toFinishListeners()
        expect(logic.values.frameSourceUrls).toEqual({})

        linked = true
        await expectLogic(logic, () =>
            logic.actions.resolveSourceUrls({ rawIds: ['linked/0'], releaseId: 'release-1' })
        ).toDispatchActions(['setSourceData'])

        expect(requests).toHaveLength(2)
        expect(logic.values.getSourceDataForFrame('linked/0', 'release-1')).toEqual({
            url: LINK_URL,
            provider: 'github',
        })
    })
})
