import { FINOPS_USAGE_OUTPUT, FinopsUsageOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'

import { FinopsUsageMeter, FinopsUsageMeterInput } from './finops-usage-meter'

function makeOutputs(): {
    outputs: IngestionOutputs<FinopsUsageOutput>
    queueMessagesMock: jest.Mock<Promise<void>, [any[]]>
} {
    const queueMessagesMock = jest.fn().mockResolvedValue(undefined)
    const fakeOutput = {
        produce: jest.fn().mockResolvedValue(undefined),
        queueMessages: queueMessagesMock,
        checkHealth: jest.fn().mockResolvedValue(undefined),
        checkTopicExists: jest.fn().mockResolvedValue(undefined),
    } as unknown as ConstructorParameters<typeof IngestionOutputs<FinopsUsageOutput>>[0][FinopsUsageOutput]
    return {
        outputs: new IngestionOutputs<FinopsUsageOutput>({ [FINOPS_USAGE_OUTPUT]: fakeOutput }),
        queueMessagesMock,
    }
}

function input(overrides: Partial<FinopsUsageMeterInput> = {}): FinopsUsageMeterInput {
    return {
        product: 'shared',
        billableUnit: 'events',
        quantity: 1000,
        teamId: 42,
        system: 'warpstream',
        workload: 'events-ingestion-consumer',
        ...overrides,
    }
}

describe('FinopsUsageMeter', () => {
    let outputs: IngestionOutputs<FinopsUsageOutput>
    let queueMessagesMock: jest.Mock<Promise<void>, [any[]]>

    beforeEach(() => {
        ;({ outputs, queueMessagesMock } = makeOutputs())
    })

    function getRows(callIndex = 0): Record<string, unknown>[] {
        const messages = queueMessagesMock.mock.calls[callIndex][0]
        return messages.map((m: { value: Buffer }) => parseJSON(m.value.toString()) as Record<string, unknown>)
    }

    it('flush is a no-op when nothing was queued', async () => {
        const meter = new FinopsUsageMeter(outputs, { enabled: true })
        await meter.flush()
        expect(queueMessagesMock).not.toHaveBeenCalled()
    })

    it('is a no-op when disabled', async () => {
        const meter = new FinopsUsageMeter(outputs, { enabled: false })
        meter.queue(input())
        await meter.flush()
        expect(queueMessagesMock).not.toHaveBeenCalled()
    })

    it('serializes exactly the usage_meters columns, with defaults for omitted dimensions', async () => {
        const meter = new FinopsUsageMeter(outputs, { enabled: true })
        meter.queue(input())
        await meter.flush()

        const row = getRows()[0]
        expect(new Set(Object.keys(row))).toEqual(
            new Set([
                'timestamp',
                'product',
                'team_id',
                'org_id',
                'feature',
                'environment',
                'billable_unit',
                'quantity',
                'system',
                'workload',
                'resource_id',
                'duration_ms',
                'service_name',
                'count',
                'cost_unit',
                'cost_quantity',
                'team',
                'cost_type',
                'user_id',
                'trace_id',
            ])
        )
        expect(row).toMatchObject({
            product: 'shared',
            team_id: 42,
            org_id: '',
            feature: '',
            billable_unit: 'events',
            quantity: 1000,
            system: 'warpstream',
            workload: 'events-ingestion-consumer',
            count: 1,
            cost_unit: '',
            cost_quantity: 0,
            team: '',
            cost_type: '',
            user_id: 0,
            trace_id: '',
        })
        expect(row.timestamp).toEqual(expect.any(String))
        expect(['dev', 'prod-us', 'prod-eu']).toContain(row.environment)
    })

    it('sums quantity and count for entries sharing the identity fields', async () => {
        const meter = new FinopsUsageMeter(outputs, { enabled: true })
        meter.queue(input({ quantity: 1000, count: 1, costQuantity: 2000 }))
        meter.queue(input({ quantity: 500, count: 1, costQuantity: 750 }))
        await meter.flush()

        const rows = getRows()
        expect(rows).toHaveLength(1)
        expect(rows[0].quantity).toBe(1500)
        expect(rows[0].count).toBe(2)
        expect(rows[0].cost_quantity).toBe(2750)
    })

    it.each([
        ['events', '$pageview', 'shared', 'events', 'ingestion'],
        ['ai_events', '$ai_generation', 'ai_observability', 'llm_events', 'ai-observability'],
        ['events', '$feature_flag_called', 'feature_flags', 'flag_requests', 'feature-flags'],
    ] as const)(
        'maps the %s output for %s to its FinOps dimensions and customer',
        async (output, eventName, product, unit, team) => {
            const meter = new FinopsUsageMeter(outputs, { enabled: true })
            meter.queueEventOutput({
                output,
                eventName,
                teamId: 42,
                orgId: 'org-42',
                byteLength: 1234,
                resourceId: `topic-${output}`,
            })
            await meter.flush()

            expect(getRows()[0]).toMatchObject({
                product,
                billable_unit: unit,
                team,
                team_id: 42,
                org_id: 'org-42',
                quantity: 1,
                cost_unit: 'bytes',
                cost_quantity: 1234,
                workload: `emit:${output}`,
                resource_id: `topic-${output}`,
            })
        }
    )

    it('aggregates captured input by customer before downstream outcomes', async () => {
        const meter = new FinopsUsageMeter(outputs, { enabled: true })
        meter.queueCapturedEvent({
            eventName: '$feature_flag_called',
            teamId: 42,
            orgId: 'org-42',
            byteLength: 100,
            resourceId: 'capture-topic',
        })
        meter.queueCapturedEvent({
            eventName: '$feature_flag_called',
            teamId: 42,
            orgId: 'org-42',
            byteLength: 250,
            resourceId: 'capture-topic',
        })
        await meter.flush()

        expect(getRows()[0]).toMatchObject({
            product: 'feature_flags',
            billable_unit: 'flag_requests',
            team: 'feature-flags',
            team_id: 42,
            org_id: 'org-42',
            quantity: 2,
            cost_unit: 'bytes',
            cost_quantity: 350,
            workload: 'consume:capture',
            resource_id: 'capture-topic',
        })
    })

    it.each([
        ['product', { product: 'cdp' }],
        ['billableUnit', { billableUnit: 'invocations' }],
        ['teamId', { teamId: 7 }],
        ['workload', { workload: 'other-consumer' }],
        ['costUnit', { costUnit: 'actions' }],
        ['team', { team: 'cdp' }],
        ['costType', { costType: 'rnd' }],
    ])('keeps %s separate', async (_field, override) => {
        const meter = new FinopsUsageMeter(outputs, { enabled: true })
        meter.queue(input())
        meter.queue(input(override as Partial<FinopsUsageMeterInput>))
        await meter.flush()

        expect(getRows()).toHaveLength(2)
    })

    it('produces with key=null and clears the buffer after flush', async () => {
        const meter = new FinopsUsageMeter(outputs, { enabled: true })
        meter.queue(input())
        await meter.flush()
        expect(queueMessagesMock.mock.calls[0][0][0].key).toBeNull()

        queueMessagesMock.mockClear()
        await meter.flush()
        expect(queueMessagesMock).not.toHaveBeenCalled()
    })
})
