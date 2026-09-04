import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { githubInstallRequestsLogic } from './githubInstallRequestsLogic'

const pendingRequest = {
    id: '018f0000-0000-7000-8000-000000000001',
    github_login: 'octocat',
    status: 'pending',
    installation_id: null,
    account_login: null,
    account_type: null,
    requested_at: '2026-08-18T00:00:00Z',
    resolved_at: null,
}

const approvedRequest = {
    ...pendingRequest,
    id: '018f0000-0000-7000-8000-000000000002',
    status: 'approved',
    installation_id: '55555',
    account_login: 'posthog-org',
    account_type: 'Organization',
    resolved_at: '2026-08-18T01:00:00Z',
}

describe('githubInstallRequestsLogic', () => {
    let logic: ReturnType<typeof githubInstallRequestsLogic.build>
    let results: Record<string, unknown>[]
    let listCalls: number
    let deletedIds: string[]

    beforeEach(() => {
        results = []
        listCalls = 0
        deletedIds = []
        useMocks({
            get: {
                '/api/users/@me/integrations/github/install_requests/': () => {
                    listCalls += 1
                    return [200, { results, install_url: 'https://github.com/apps/posthog-dev/installations/new' }]
                },
            },
            delete: {
                '/api/users/@me/integrations/github/install_requests/:id/': ({ params }) => {
                    deletedIds.push(String(params.id))
                    return deletedIds.length === 1 ? [204] : [404, { detail: 'No GitHub install request found.' }]
                },
            },
        })
        initKeaTests()
        logic = githubInstallRequestsLogic()
    })

    afterEach(() => {
        jest.useRealTimers()
        logic.unmount()
    })

    it('splits requests by status and exposes the shareable install url', async () => {
        results = [pendingRequest, approvedRequest]
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadInstallRequestsSuccess'])

        expect(logic.values.pendingInstallRequests.map((r) => r.id)).toEqual([pendingRequest.id])
        expect(logic.values.approvedInstallRequests.map((r) => r.id)).toEqual([approvedRequest.id])
        expect(logic.values.installUrl).toBe('https://github.com/apps/posthog-dev/installations/new')
    })

    it.each([
        ['pending request with a subscriber', [pendingRequest], true, true],
        ['pending request without a subscriber', [pendingRequest], false, false],
        ['only approved requests with a subscriber', [approvedRequest], true, false],
    ])('polls only when %s', async (_name, rows, subscribed, expectPolling) => {
        results = rows
        jest.useFakeTimers()
        logic.mount()
        if (subscribed) {
            logic.actions.startPolling()
        }

        await expectLogic(logic).toDispatchActions(['loadInstallRequestsSuccess'])

        expect(logic.cache.disposables.registry.has('poll')).toBe(expectPolling)
    })

    it('stops polling once the last subscriber leaves and refetches on the interval while subscribed', async () => {
        results = [pendingRequest]
        jest.useFakeTimers()
        logic.mount()
        logic.actions.startPolling()
        logic.actions.startPolling()
        await expectLogic(logic).toDispatchActions(['loadInstallRequestsSuccess'])
        const callsBeforeTick = listCalls

        jest.advanceTimersByTime(15_000)
        await expectLogic(logic).toDispatchActions(['loadInstallRequests', 'loadInstallRequestsSuccess'])
        expect(listCalls).toBe(callsBeforeTick + 1)

        logic.actions.stopPolling()
        expect(logic.cache.disposables.registry.has('poll')).toBe(true)
        logic.actions.stopPolling()
        expect(logic.cache.disposables.registry.has('poll')).toBe(false)
    })

    it('retries on the interval when the first load fails', async () => {
        useMocks({
            get: {
                '/api/users/@me/integrations/github/install_requests/': () => {
                    listCalls += 1
                    return listCalls === 1
                        ? [500, { detail: 'Server error.' }]
                        : [200, { results: [pendingRequest], install_url: null }]
                },
            },
        })
        jest.useFakeTimers()
        logic.mount()
        logic.actions.startPolling()

        await expectLogic(logic).toDispatchActions(['loadInstallRequestsFailure'])
        expect(logic.cache.disposables.registry.has('poll')).toBe(true)

        jest.advanceTimersByTime(15_000)
        await expectLogic(logic).toDispatchActions(['loadInstallRequestsSuccess'])
        expect(logic.values.pendingInstallRequests.map((r) => r.id)).toEqual([pendingRequest.id])
    })

    it('gives up polling once the endpoint keeps failing', async () => {
        useMocks({
            get: {
                '/api/users/@me/integrations/github/install_requests/': () => {
                    listCalls += 1
                    return [500, { detail: 'Server error.' }]
                },
            },
        })
        jest.useFakeTimers()
        logic.mount()
        logic.actions.startPolling()

        await expectLogic(logic).toDispatchActions(['loadInstallRequestsFailure'])
        for (let attempt = 0; attempt < 2; attempt++) {
            expect(logic.cache.disposables.registry.has('poll')).toBe(true)
            jest.advanceTimersByTime(15_000)
            await expectLogic(logic).toDispatchActions(['loadInstallRequestsFailure'])
        }

        expect(logic.cache.disposables.registry.has('poll')).toBe(false)
        const callsAfterGivingUp = listCalls
        jest.advanceTimersByTime(60_000)
        expect(listCalls).toBe(callsAfterGivingUp)
    })

    it('reloads after dismissing, and treats an already-deleted request as dismissed', async () => {
        results = [pendingRequest]
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadInstallRequestsSuccess'])

        results = []
        await expectLogic(logic, () => {
            logic.actions.dismissInstallRequest(pendingRequest.id)
        }).toDispatchActions(['loadInstallRequests', 'loadInstallRequestsSuccess'])
        expect(logic.values.pendingInstallRequests).toEqual([])

        await expectLogic(logic, () => {
            logic.actions.dismissInstallRequest(pendingRequest.id)
        }).toDispatchActions(['loadInstallRequests', 'loadInstallRequestsSuccess'])
        expect(deletedIds).toEqual([pendingRequest.id, pendingRequest.id])
    })

    it('marks a request as dismissing while its delete is in flight, then clears it', async () => {
        results = [pendingRequest]
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadInstallRequestsSuccess'])

        results = []
        // The reducer applies synchronously on dispatch, before the DELETE resolves, so the button
        // can disable itself for the duration.
        logic.actions.dismissInstallRequest(pendingRequest.id)
        expect(logic.values.dismissingRequestIds).toEqual([pendingRequest.id])

        await expectLogic(logic).toDispatchActions(['dismissInstallRequestSuccess', 'loadInstallRequestsSuccess'])
        expect(logic.values.dismissingRequestIds).toEqual([])
    })
})
