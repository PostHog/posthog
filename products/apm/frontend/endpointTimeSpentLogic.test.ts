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

    beforeEach(() => {
        requests = []
        useMocks({
            get: {
                '/api/projects/:team_id/apm/endpoint_time_spent/': ({ request }) => {
                    requests.push(new URL(request.url).searchParams)
                    return [200, RESPONSE]
                },
                '/api/projects/:team_id/apm/services/': () => [
                    200,
                    { results: [], environments: [], environment: 'prod' },
                ],
            },
        })
        initKeaTests()
    })

    it('loads the row it was opened for over the scene time range, and reloads when the range changes', async () => {
        const scene = applicationObservabilityLogic()
        scene.mount()
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
        await expectLogic(logic).toDispatchActions(['loadTimeSpentSuccess'])
        const second = requests[requests.length - 1]
        expect(Date.parse(second.get('date_to')!) - Date.parse(second.get('date_from')!)).toBe(24 * 60 * 60 * 1000)

        logic.unmount()
        scene.unmount()
    })
})
