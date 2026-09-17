import { createCustomerJourney, CustomerJourneyContext, CustomerJourneyDependencies } from './createCustomerJourney'

const context: CustomerJourneyContext = {
    journey_name: 'dashboard_refresh',
    resource_type: 'dashboard',
    resource_id: 'synthetic-dashboard',
    trigger: 'initial_load',
    readiness_contract_version: 1,
    readiness_scope: 'visible_product_analytics_tiles',
    attempt_id: 'synthetic-attempt',
    region: 'US',
    project_id: 101,
    organization_id: 'synthetic-organization',
    registry_version: 'test-v1',
}

function boundary(): {
    dependencies: CustomerJourneyDependencies
    capture: jest.Mock
    listeners: Set<() => void>
    setTime: (value: number) => void
    setVisibility: (value: DocumentVisibilityState) => void
} {
    let time = 100
    let visibility: DocumentVisibilityState = 'visible'
    const listeners = new Set<() => void>()
    const capture = jest.fn()
    const dependencies: CustomerJourneyDependencies = {
        now: () => time,
        capture,
        visibility: {
            getState: () => visibility,
            subscribe: (listener) => {
                listeners.add(listener)
                return () => listeners.delete(listener)
            },
        },
    }
    return {
        dependencies,
        capture,
        listeners,
        setTime: (value: number) => (time = value),
        setVisibility: (value: DocumentVisibilityState) => {
            visibility = value
            listeners.forEach((listener) => listener())
        },
    }
}

describe('customer journey lifecycle', () => {
    it('emits start synchronously, snapshots context and finishes once with the first useful milestone', () => {
        const b = boundary()
        const mutableContext = { ...context }
        const journey = createCustomerJourney(mutableContext, b.dependencies)!
        expect(b.capture.mock.calls).toEqual([
            ['customer_journey_started', { ...context, schema_version: 1, visibility_state: 'visible' }],
        ])
        mutableContext.project_id = 202
        b.setTime(150)
        journey.firstUseful()
        b.setTime(180)
        journey.firstUseful()
        b.setTime(200)
        journey.finish('usable', { total_count: 4, ready_count: 4 })
        journey.finish('failed', { error_type: 'query_error' })
        journey.dispose('exited')
        expect(b.capture.mock.calls).toHaveLength(2)
        expect(b.capture.mock.calls[1]).toEqual([
            'customer_journey_finished',
            {
                ...context,
                schema_version: 1,
                visibility_state: 'visible',
                outcome: 'usable',
                duration_ms: 100,
                foreground_duration_ms: 100,
                first_useful_ms: 50,
                total_count: 4,
                ready_count: 4,
            },
        ])
        expect(b.listeners.size).toBe(0)
    })

    it('records coverage and bounded per-type counts without leaking unknown metadata or invalid numbers', () => {
        const b = boundary()
        const journey = createCustomerJourney(
            {
                ...context,
                readiness_scope: 'visible_product_analytics_tiles',
            },
            b.dependencies
        )!
        const summary = {
            excluded_count: 2,
            exposures_response_cached: true,
            insight_type_summary: {
                RETENTION: {
                    total_count: 2,
                    ready_count: 1,
                    failed_count: 1,
                    max_duration_ms: 30.5,
                    query: 'synthetic query',
                },
                TRENDS: { total_count: -1, ready_count: 0, failed_count: 0 },
                FUNNELS: { total_count: 1, ready_count: 1, failed_count: 0, max_duration_ms: Infinity },
                SQL: { total_count: 1, ready_count: 1, failed_count: 0 },
            },
            raw_payload: 'synthetic payload',
        }
        journey.finish('failed', summary)
        expect(b.capture.mock.calls[0][1]).toMatchObject({ readiness_scope: 'visible_product_analytics_tiles' })
        expect(b.capture.mock.calls[1][1]).toEqual({
            ...context,
            schema_version: 1,
            visibility_state: 'visible',
            readiness_scope: 'visible_product_analytics_tiles',
            outcome: 'failed',
            duration_ms: 0,
            foreground_duration_ms: 0,
            excluded_count: 2,
            exposures_response_cached: true,
            insight_type_summary: {
                RETENTION: { total_count: 2, ready_count: 1, failed_count: 1, max_duration_ms: 30.5 },
                FUNNELS: { total_count: 1, ready_count: 1, failed_count: 0 },
            },
        })
    })

    it.each([false, 'true', undefined])('projects only boolean exposure cache evidence (%s)', (value) => {
        const b = boundary()
        const journey = createCustomerJourney(context, b.dependencies)!
        journey.finish('usable', { exposures_response_cached: value } as any)
        const event = b.capture.mock.calls[1][1]
        if (typeof value === 'boolean') {
            expect(event.exposures_response_cached).toBe(value)
        } else {
            expect(event).not.toHaveProperty('exposures_response_cached')
        }
    })

    it('accumulates foreground time without treating a hidden document as an exit', () => {
        const b = boundary()
        const journey = createCustomerJourney(context, b.dependencies)!
        b.setTime(120)
        b.setVisibility('hidden')
        b.setTime(200)
        expect(b.capture.mock.calls).toHaveLength(1)
        b.setVisibility('visible')
        b.setTime(230)
        journey.finish('usable')
        expect(b.capture.mock.calls[1][1]).toMatchObject({ duration_ms: 130, foreground_duration_ms: 50 })
        expect(b.listeners.size).toBe(0)
    })

    it('keeps callbacks from a superseded handle from completing the replacement attempt', () => {
        const b = boundary()
        const old = createCustomerJourney(context, b.dependencies)!
        old.dispose('superseded')
        const replacement = createCustomerJourney({ ...context, attempt_id: 'synthetic-replacement' }, b.dependencies)!
        old.finish('usable')
        replacement.finish('failed', { error_type: 'query_error' })
        expect(
            b.capture.mock.calls.filter(([event]) => event === 'customer_journey_finished').map(([, props]) => props)
        ).toEqual([
            expect.objectContaining({
                attempt_id: context.attempt_id,
                outcome: 'superseded',
                end_reason: 'superseded',
            }),
            expect.objectContaining({ attempt_id: 'synthetic-replacement', outcome: 'failed' }),
        ])
        expect(b.listeners.size).toBe(0)
    })

    it.each(['start', 'finish'] as const)(
        'contains capture errors at %s and cleans up without inventing a finish',
        (stage) => {
            const b = boundary()
            if (stage === 'start') {
                b.capture.mockImplementation(() => {
                    throw new Error('synthetic telemetry error')
                })
            }
            const journey = createCustomerJourney(context, b.dependencies)
            if (stage === 'start') {
                expect(journey).toBeNull()
            } else {
                b.capture.mockImplementation(() => {
                    throw new Error('synthetic telemetry error')
                })
                expect(() => journey!.finish('usable')).not.toThrow()
                journey!.finish('failed')
            }
            expect(b.capture.mock.calls).toHaveLength(stage === 'start' ? 1 : 2)
            expect(b.listeners.size).toBe(0)
        }
    )
})
