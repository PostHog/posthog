import type { LogRecord } from '~/logs/log-record-avro'
import { runPipelineStages } from '~/logs/pipeline/log-processing-pipeline'

import { compileRetentionRuleSet } from './compile-retention-rules'
import { makeRetentionStage } from './retention-stage'

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
            [makeRetentionStage(ruleSet, 1, 14)]
        )
        // 'api' matches the 30-day rule; 'billing' matches nothing so it takes the team default.
        expect(kept.map((r) => r.retention_days)).toEqual([30, 14])
    })
})
