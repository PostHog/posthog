import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { parseTagsFilter } from 'lib/utils/url'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import {
    APPLICATION_OBSERVABILITY_PATH,
    applicationObservabilityLogic,
    drillDownParams,
} from './applicationObservabilityLogic'
import type { ServicesHealthResponseApi } from './generated/api.schemas'

const row = (service_name: string, status: 'good' | 'warning' | 'serious' | 'critical'): any => ({
    service_name,
    environment: 'prod',
    status,
    health: { request_rate: 1, error_rate: 0, p95_ms: 10, span_count: 1, error_count: 0 },
    sparkline: [1],
})

const RESPONSE: ServicesHealthResponseApi = {
    results: [row('queue', 'serious'), row('web', 'warning'), row('api', 'good')],
    environments: ['prod', 'staging'],
    environment: 'prod',
    date_from: '2026-06-02T07:00:00Z',
    date_to: '2026-06-02T08:00:00Z',
}

describe('applicationObservabilityLogic', () => {
    let logic: ReturnType<typeof applicationObservabilityLogic.build>
    let requests: string[]

    beforeEach(async () => {
        requests = []
        useMocks({
            get: {
                '/api/projects/:team_id/apm/services/': ({ request }) => {
                    requests.push(new URL(request.url).search)
                    return [200, RESPONSE]
                },
            },
        })
        initKeaTests()
        logic = applicationObservabilityLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('counts the services that need attention from the loaded rows', async () => {
        await expectLogic(logic).toDispatchActions(['loadServicesHealthSuccess'])
        expect(logic.values.attentionCount).toBe(1)
        expect(logic.values.environments).toEqual(['prod', 'staging'])
        expect(logic.values.resolvedEnvironment).toBe('prod')
        // Mounting with no URL params must load exactly once: a prior bug fired both the
        // urlToAction initial sync and afterMount's own load.
        expect(requests.length).toBe(1)
    })

    it('round-trips environment and range through the URL and reloads once per change', async () => {
        await expectLogic(logic).toDispatchActions(['loadServicesHealthSuccess'])
        const before = requests.length

        router.actions.push(APPLICATION_OBSERVABILITY_PATH, { environment: 'staging', range: '-24h' })
        await expectLogic(logic).toDispatchActions(['setEnvironment', 'setTimeRange', 'loadServicesHealthSuccess'])
        expect(logic.values.environment).toBe('staging')
        expect(logic.values.timeRange).toBe('-24h')
        expect(requests.length).toBe(before + 1)
        expect(requests[requests.length - 1]).toContain('environment=staging')

        logic.actions.setTimeRange('-6h')
        expect(router.values.searchParams).toMatchObject({ environment: 'staging', range: '-6h' })
    })

    it('reloads when a picker action fires directly, not only via a URL round-trip', async () => {
        // Dispatching setEnvironment directly (as the scene's LemonSelect onChange does) used to
        // skip the reload: by the time urlToAction re-read the URL it had already written, the
        // values already matched and the `changed` guard stayed false.
        await expectLogic(logic).toDispatchActions(['loadServicesHealthSuccess'])
        const before = requests.length

        logic.actions.setEnvironment('direct-pick')
        await expectLogic(logic).toDispatchActions(['loadServicesHealthSuccess'])

        expect(requests.length).toBe(before + 1)
    })

    it('tracks a refresh failure separately from the loaded data, so stale data is not reported as healthy', async () => {
        await expectLogic(logic).toDispatchActions(['loadServicesHealthSuccess'])
        expect(logic.values.hasLoadError).toBe(false)
        expect(logic.values.services).toHaveLength(3)

        useMocks({ get: { '/api/projects/:team_id/apm/services/': () => [500, { detail: 'boom' }] } })
        logic.actions.loadServicesHealth()
        await expectLogic(logic).toDispatchActions(['loadServicesHealthFailure'])

        expect(logic.values.hasLoadError).toBe(true)
        // The previous successful rows stay in `services` so the scene can show them as stale
        // instead of losing them, which is what let a failed refresh render as "All quiet".
        expect(logic.values.services).toHaveLength(3)
    })

    it('ignores an unknown range in the URL and keeps the default', async () => {
        router.actions.push(APPLICATION_OBSERVABILITY_PATH, { range: 'yesterday' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.timeRange).toBe('-1h')
    })

    it('ignores an inherited-property range value in the URL', async () => {
        // `in` matches inherited Object.prototype keys like `toString`, so a naive `value in
        // TIME_RANGE_LABELS` check would accept this and break TIME_RANGE_MS lookups.
        router.actions.push(APPLICATION_OBSERVABILITY_PATH, { range: 'toString' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.timeRange).toBe('-1h')
    })

    it('keeps a service name with a comma as one service in drill-down links', () => {
        const params = new URLSearchParams(drillDownParams('checkout,v2', '-1h'))
        expect(parseTagsFilter(params.get('serviceNames'))).toEqual(['checkout,v2'])
    })
})
