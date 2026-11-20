import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { applicationObservabilityLogic } from './applicationObservabilityLogic'
import { endpointTimeSpentLogic } from './endpointTimeSpentLogic'
import type { EndpointTimeSpentResponseApi } from './generated/api.schemas'

const RESPONSE: EndpointTimeSpentResponseApi = {
    components: [
        { name: 'payments', kind: 'service', total_ms: 100, avg_ms_per_request: 50, share: 0.5 },
        { name: 'postgresql', kind: 'inferred', total_ms: 100, avg_ms_per_request: 50, share: 0.5 },
    ],
    request_count: 2,
    avg_duration_ms: 100,
    service: 'checkout',
    endpoint: 'POST /orders',
    environment: 'prod',
    date_from: '2026-06-02T07:00:00Z',
    date_to: '2026-06-02T08:00:00Z',
}

describe('endpointTimeSpentLogic', () => {
    let requests: URLSearchParams[]
    let failNext: boolean

    beforeEach(() => {
        requests = []
        failNext = false
        useMocks({
            get: {
                '/api/projects/:team_id/apm/endpoint_time_spent/': ({ request }) => {
                    requests.push(new URL(request.url).searchParams)
                    return failNext ? [500, {}] : [200, RESPONSE]
                },
                '/api/projects/:team_id/apm/endpoints/': () => [200, { results: [], environment: 'prod' }],
                '/api/projects/:team_id/apm/services/': () => [
                    200,
                    { results: [], environments: [], environment: 'prod' },
                ],
            },
        })
        initKeaTests()
    })

    it('loads the row it was opened for, reloads with the endpoints table, and keeps the last result on a failed refresh', async () => {
        const scene = applicationObservabilityLogic()
        scene.mount()
        scene.actions.setTab('endpoints')
        const logic = endpointTimeSpentLogic({ service: 'checkout', endpoint: 'POST /orders', environment: 'prod' })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadTimeSpentSuccess'])
        expect(logic.values.timeSpent).toEqual(RESPONSE)
        const first = requests[requests.length - 1]
        expect([first.get('service'), first.get('endpoint'), first.get('environment')]).toEqual([
            'checkout',
            'POST /orders',
            'prod',
        ])
        const hourMs = Date.parse(first.get('date_to')!) - Date.parse(first.get('date_from')!)
        expect(hourMs).toBe(60 * 60 * 1000)

        scene.actions.setTimeRange('-24h')
        await expectLogic(logic).toDispatchActions(['loadEndpointsHealthSuccess', 'loadTimeSpentSuccess'])
        const second = requests[requests.length - 1]
        expect(Date.parse(second.get('date_to')!) - Date.parse(second.get('date_from')!)).toBe(24 * 60 * 60 * 1000)

        failNext = true
        logic.actions.loadTimeSpent()
        await expectLogic(logic).toDispatchActions(['loadTimeSpentFailure'])
        expect(logic.values).toMatchObject({ timeSpent: RESPONSE, timeSpentFailed: true })

        logic.unmount()
        scene.unmount()
    })
})
