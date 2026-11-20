import { PropertyFilterType, PropertyOperator } from '~/types'

import { MeasureEnumApi } from 'products/alerts_platform/frontend/generated/api.schemas'
import { buildTargetPresetForm } from 'products/tracing/frontend/alerting/tracesAlertPresets'
import { toWritePayload, validateForm } from 'products/tracing/frontend/alerting/tracesAlertUtils'

import { endpointAlertTarget, serviceAlertTarget } from './alertPresets'
import type { EndpointHealthApi, ServiceHealthApi } from './generated/api.schemas'

const health = { request_rate: 2, error_rate: 0.04, p95_ms: 400, span_count: 1000, error_count: 40, apdex: 0.9 }

const SERVICE_ROW: ServiceHealthApi = {
    service_name: 'checkout-api',
    environment: 'production',
    status: 'warning',
    health,
    sparkline: [1, 2],
}

const ENDPOINT_ROW: EndpointHealthApi = {
    service_name: 'checkout-api',
    endpoint: 'POST /cart',
    span_name: 'POST /cart',
    route_attribute: null,
    route: null,
    environment: 'production',
    status: 'warning',
    health,
}

const endpointFilter = (name: string): object => ({
    type: 'AND',
    values: [
        {
            type: 'AND',
            values: [{ type: PropertyFilterType.Span, key: 'name', operator: PropertyOperator.Exact, value: [name] }],
        },
    ],
})

describe('APM alert presets', () => {
    it.each([
        ['service', serviceAlertTarget(SERVICE_ROW), null, 'checkout-api: p95 latency'],
        [
            'endpoint',
            endpointAlertTarget(ENDPOINT_ROW),
            endpointFilter('POST /cart'),
            'checkout-api POST /cart: p95 latency',
        ],
        // A bare-method span is labelled with its route: the alert filters on the span name and the route, so other routes of the same method don't count.
        [
            'route-labelled endpoint',
            endpointAlertTarget({
                ...ENDPOINT_ROW,
                endpoint: 'GET /orders',
                span_name: 'GET',
                route_attribute: 'http.route',
                route: '/orders',
            }),
            {
                type: 'AND',
                values: [
                    {
                        type: 'AND',
                        values: [
                            {
                                type: PropertyFilterType.Span,
                                key: 'name',
                                operator: PropertyOperator.Exact,
                                value: ['GET'],
                            },
                            {
                                type: PropertyFilterType.SpanAttribute,
                                key: 'http.route',
                                operator: PropertyOperator.Exact,
                                value: ['/orders'],
                            },
                        ],
                    },
                ],
            },
            'checkout-api GET /orders: p95 latency',
        ],
        // An empty span name is still one endpoint, not the whole service.
        [
            'endpoint with an empty name',
            endpointAlertTarget({ ...ENDPOINT_ROW, endpoint: '', span_name: '' }),
            endpointFilter(''),
            'checkout-api: p95 latency',
        ],
    ])('scopes a %s row alert to that row', (_, target, filterGroup, name) => {
        const form = buildTargetPresetForm(target, 'p95_latency')

        expect(validateForm(form)).toEqual({})
        const payload = toWritePayload(form)
        expect(payload.name).toBe(name)
        expect(payload.source_config).toEqual({
            filters: { serviceNames: ['checkout-api'], filterGroup },
            condition: expect.objectContaining({ measure: MeasureEnumApi.Latency, percentile: 95, threshold: 600 }),
        })
    })

    it('sets the error rate threshold from the row error count', () => {
        const payload = toWritePayload(buildTargetPresetForm(serviceAlertTarget(SERVICE_ROW), 'error_rate'))

        expect(payload.source_config.condition).toEqual(
            expect.objectContaining({ measure: MeasureEnumApi.ErrorRate, threshold: 0.06 })
        )
    })
})
