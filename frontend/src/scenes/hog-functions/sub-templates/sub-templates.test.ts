import { SAMPLE_GLOBALS_CONTEXTS } from 'scenes/hog-functions/configuration/sampleGlobalsContexts'

import { CyclotronJobInvocationGlobals, PropertyFilterType, PropertyOperator } from '~/types'

import { HOG_FUNCTION_SUB_TEMPLATES, eventToHogFunctionContextId } from './sub-templates'

describe('sub-templates', () => {
    // One event per product that creates internal destinations. An id missing from the switch
    // falls back to 'standard', which merges that product into the notification list's "Other"
    // source and drops its source tag.
    it.each([
        ['$error_tracking_issue_created', 'error-tracking'],
        ['$insight_alert_firing', 'insight-alerts'],
        ['$experiment_metric_significant', 'experiment-alerts'],
        ['$activity_log_entry_created', 'activity-log'],
        ['$discussion_mention_created', 'discussion-mention'],
        ['$logs_alert_firing', 'logs-alerting'],
        ['$health_check_issue_firing', 'health-alerts'],
        ['$batch_export_run_failed', 'batch-export-alerts'],
        ['$billing_alert_firing', 'billing-alerts'],
        ['$replay_vision_alert_match', 'replay-vision-alerts'],
        ['$pageview', 'standard'],
        [undefined, 'standard'],
    ])('reads %s as the %s context', (event, expected) => {
        expect(eventToHogFunctionContextId(event)).toBe(expected)
    })

    // A placeholder the sample event leaves empty renders an empty Slack block. Slack then rejects
    // the whole test message.
    it.each(['health-check-firing', 'health-check-resolved'] as const)(
        'gives the %s templates a sample value for every event property they read',
        async (subTemplateId) => {
            const sample = await SAMPLE_GLOBALS_CONTEXTS['health-alerts']!({
                event: { properties: {} },
            } as CyclotronJobInvocationGlobals)
            const inputs = JSON.stringify(HOG_FUNCTION_SUB_TEMPLATES[subTemplateId].map((template) => template.inputs))
            const readProperties = new Set([...inputs.matchAll(/event\.properties\.(\w+)/g)].map((match) => match[1]))

            expect(readProperties.size).toBeGreaterThan(0)
            for (const property of readProperties) {
                expect([property, sample.event.properties[property] ?? '']).not.toEqual([property, ''])
            }
        }
    )

    // An alert scoped to some kinds skips a sample event of any other kind, so its test sends nothing.
    it.each([
        ['the first kind of an exact kind filter', PropertyOperator.Exact, 'external_data_failure'],
        ['a placeholder kind for a filter that excludes kinds', PropertyOperator.IsNot, 'test'],
        ['a placeholder kind with no kind filter', null, 'test'],
    ])('gives the health sample event %s', async (_, operator, expected) => {
        const sample = await SAMPLE_GLOBALS_CONTEXTS['health-alerts']!(
            { event: { properties: {} } } as CyclotronJobInvocationGlobals,
            {
                events: [{ id: '$health_check_issue_firing', type: 'events' }],
                properties: operator
                    ? [
                          {
                              key: 'kind',
                              value: ['external_data_failure', 'sdk_outdated'],
                              operator,
                              type: PropertyFilterType.Event,
                          },
                      ]
                    : [],
            }
        )
        expect(sample.event.properties.kind).toBe(expected)
    })
})
