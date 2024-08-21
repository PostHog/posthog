import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { errorTrackingGroupSceneLogic } from './errorTrackingGroupSceneLogic'

const errorTrackingGroup = {
    fingerprint: ['my', 'error', 'fingerprint'],
    exception_type: 'Error',
    merged_fingerprints: [],
    occurrences: 500,
    sessions: 200,
    users: 100,
    description: 'error description',
    first_seen: '2024-08-20T09:46:22.156000Z',
    last_seen: '2024-08-20T09:46:22.156000Z',
    volume: null,
    assignee: null,
    status: 'active',
    events: [
        {
            timestamp: '2024-08-20T09:46:22.167000Z',
            uuid: '01916f2e-2a51-7254-a7b1-7a9a77692d49',
            properties: JSON.stringify({
                $os: 'Mac OS X',
                $os_version: '10.15.7',
                $browser: 'Chrome',
                $device_type: 'Desktop',
                $lib: 'web',
                $lib_version: '1.156.1',
                $exception_type: 'Error',
                $exception_message: 'error message',
                $exception_level: 'error',
                $exception_fingerprint: ['my', 'error', 'fingerprint'],
            }),
        },
    ],
}

describe('errorTrackingGroupSceneLogic', () => {
    let logic: ReturnType<typeof errorTrackingGroupSceneLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/projects/:team_id/query/': {
                    results: [errorTrackingGroup],
                },
            },
        })
        initKeaTests()
    })

    describe('fetching group', () => {
        it('appends extra errors to the existing group', async () => {
            logic = errorTrackingGroupSceneLogic({
                fingerprint: ['my', 'error', 'fingerprint'],
            })

            logic.mount()

            await expectLogic(logic).toFinishAllListeners().toMatchValues({ group: errorTrackingGroup })

            await expectLogic(logic, () => {
                logic.actions.loadMoreErrors()
            })
                .toFinishAllListeners()
                .toMatchValues({ group: expect.objectContaining({ fingerprint: ['my', 'error', 'fingerprint'] }) })

            expect(logic.values.group?.events?.length).toEqual(2)
        })
    })
})
