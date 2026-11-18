import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as apmApi from '../generated/api'
import type { ServicesHealthResponseApi } from '../generated/api.schemas'
import { readScopeParam } from './servicePage'
import { servicePageLogic, servicePageStateFromUrl } from './servicePageLogic'

const EMPTY_HEALTH = { results: [], environments: [], environment: 'production' }

describe('servicePageLogic', () => {
    let logic: ReturnType<typeof servicePageLogic.build>
    let servicesRequestCount: number
    let servicesStatus: number

    beforeEach(() => {
        servicesRequestCount = 0
        servicesStatus = 200
        const servicesHandler = (): [number, typeof EMPTY_HEALTH] => {
            servicesRequestCount += 1
            return [servicesStatus, EMPTY_HEALTH]
        }
        useMocks({
            get: {
                '/api/environments/:teamId/apm/services/': servicesHandler,
                '/api/projects/:teamId/apm/services/': servicesHandler,
            },
            post: {
                '/api/projects/:teamId/tracing/spans/attribute-breakdown/': async ({ request }) => {
                    const { query } = (await request.json()) as { query: { breakdownKey: string } }
                    // This team writes its environment under the legacy `env` key only.
                    const values: Record<string, string[]> = { env: ['production'], 'service.version': ['1.2.0'] }
                    return [
                        200,
                        {
                            results: (values[query.breakdownKey] ?? []).map((value) => ({
                                value,
                                count: 10,
                                error_count: 1,
                                p50_duration_nano: 1,
                                p95_duration_nano: 2,
                            })),
                            compare: null,
                        },
                    ]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it.each([
        ['a plain name', 'checkout', {}],
        [
            'a name with a comma and a full scope',
            'checkout,v2',
            { range: '-24h', environment: 'prod', version: '1.0', operation: 'GET /a' },
        ],
        ['values the router would read as a number or a boolean', '2024', { environment: 'true', version: '10' }],
    ])('a service link round-trips through the page URL for %s', (_, serviceName, params) => {
        router.actions.push(urls.applicationObservabilityService(serviceName, params))

        const { range = '-1h', ...scope } = params as Record<string, string>
        expect(readScopeParam(router.values.searchParams.service)).toBe(serviceName)
        expect(servicePageStateFromUrl(router.values.searchParams)).toEqual({
            timeRange: range,
            scope: { environment: null, version: null, operation: null, ...scope },
        })
    })

    it('restores the scope from the URL and writes changes back to it', async () => {
        router.actions.push(
            urls.applicationObservabilityService('checkout', { environment: 'production', operation: 'GET /cart' })
        )
        logic = servicePageLogic({ serviceName: 'checkout' })
        logic.mount()

        expect(logic.values.scope).toEqual({ environment: 'production', version: null, operation: 'GET /cart' })
        await expectLogic(logic).toFinishAllListeners()
        const servicesRequestsBefore = servicesRequestCount

        logic.actions.setScope({ operation: null, version: '2.0' })
        expect(servicePageStateFromUrl(router.values.searchParams)).toEqual({
            timeRange: '-1h',
            scope: { environment: 'production', version: '2.0', operation: null },
        })
        // The health API doesn't take a version or an operation, so it isn't asked again.
        await expectLogic(logic).toFinishAllListeners()
        expect(servicesRequestCount).toBe(servicesRequestsBefore)
    })

    it('aborts a superseded health request without reporting it as a failed load', async () => {
        logic = servicePageLogic({ serviceName: 'checkout' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        const signals: AbortSignal[] = []
        jest.spyOn(apmApi, 'apmServicesList').mockImplementation((_, __, options) => {
            const signal = options!.signal!
            signals.push(signal)
            if (signals.length > 1) {
                return Promise.resolve({ ...EMPTY_HEALTH, date_from: '', date_to: '' })
            }
            return new Promise<ServicesHealthResponseApi>((_resolve, reject) =>
                signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
            )
        })

        const first = logic.asyncActions.fetchServicesHealth()
        await expectLogic(logic).delay(20)
        await logic.asyncActions.fetchServicesHealth()
        await first

        expect(signals.map((signal) => signal.aborted)).toEqual([true, false])
        expect(logic.values.servicesHealthFailed).toBe(false)
    })

    it('marks a failed health load instead of showing the previous response as current', async () => {
        logic = servicePageLogic({ serviceName: 'checkout' })
        logic.mount()
        await logic.asyncActions.fetchServicesHealth()
        expect(logic.values.servicesHealthFailed).toBe(false)

        servicesStatus = 500
        await expectLogic(logic, () => logic.actions.fetchServicesHealth())
            .toDispatchActions(['fetchServicesHealthFailure'])
            .toMatchValues({ servicesHealthFailed: true })
    })

    it('filters spans on the environment key the team emits', async () => {
        router.actions.push(
            urls.applicationObservabilityService('checkout', { environment: 'production', operation: 'GET /cart' })
        )
        logic = servicePageLogic({ serviceName: 'checkout' })
        logic.mount()

        await logic.asyncActions.fetchScopeOptions()

        expect(logic.values.environmentKey).toBe('env')
        expect(logic.values.scopeFilters).toEqual([
            { type: 'span_resource_attribute', key: 'env', operator: 'exact', value: ['production'] },
            { type: 'span', key: 'name', operator: 'exact', value: ['GET /cart'] },
        ])
    })
})
