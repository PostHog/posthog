import type { LogRecord } from '~/logs/log-record-avro'
import { runPipelineStages } from '~/logs/pipeline/log-processing-pipeline'

import { compileRetentionRuleSet } from './compile-retention-rules'
import { logsRetentionRowsStampedCounter, makeRetentionStage } from './retention-stage'

async function stampedCount(teamId: string, matched: 'true' | 'false'): Promise<number> {
    const metric = await logsRetentionRowsStampedCounter.get()
    return metric.values.find((v) => v.labels.team_id === teamId && v.labels.matched === matched)?.value ?? 0
}

describe('makeRetentionStage', () => {
    const record = (service: string): LogRecord => ({
        uuid: null,
        trace_id: null,
        span_id: null,
        trace_flags: null,
        timestamp: null,
        observed_timestamp: null,
        body: 'x',
        severity_text: 'info',
        severity_number: 9,
        service_name: service,
        resource_attributes: null,
        instrumentation_scope: null,
        event_name: null,
        attributes: null,
    })

    const serviceRule = (id: string, service: string, retentionDays: number) => ({
        id,
        config: {
            retention_days: retentionDays,
            filter_group: {
                type: 'AND',
                values: [
                    {
                        type: 'AND',
                        values: [
                            { key: 'service.name', type: 'log_resource_attribute', operator: 'exact', value: service },
                        ],
                    },
                ],
            },
        },
    })

    it('stamps the matched rule value and the team default on non-matching records', async () => {
        const ruleSet = compileRetentionRuleSet([serviceRule('a', 'api', 30)])
        const { kept } = await runPipelineStages(
            [record('api'), record('billing')],
            [makeRetentionStage(ruleSet, 4242, 14)]
        )
        // 'api' matches the 30-day rule; 'billing' matches nothing so it takes the team default.
        expect(kept.map((r) => r.retention_days)).toEqual([30, 14])
        // The counter split mirrors matching: one rule-matched row, one team-default row.
        expect(await stampedCount('4242', 'true')).toBe(1)
        expect(await stampedCount('4242', 'false')).toBe(1)
    })
})
