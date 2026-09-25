import { CyclotronJobFiltersType, PropertyFilterType, PropertyOperator } from '~/types'

import { setSimpleFilterValue } from './HogFunctionFiltersInternal'

describe('setSimpleFilterValue', () => {
    const options = [
        { label: 'Team activity', value: '$activity_log_entry_created' },
        { label: 'Early access feature updated', value: '$early_access_feature_updated' },
    ]
    // As created from one flag's Notifications tab
    const boundToFlag: CyclotronJobFiltersType = {
        source: 'internal-events',
        events: [
            {
                id: '$activity_log_entry_created',
                type: 'events',
                properties: [
                    {
                        key: 'scope',
                        type: PropertyFilterType.Event,
                        value: ['FeatureFlag'],
                        operator: PropertyOperator.Exact,
                    },
                ],
            },
        ],
        properties: [
            { key: 'item_id', type: PropertyFilterType.Event, value: ['42'], operator: PropertyOperator.Exact },
        ],
    }

    it('keeps a resource-bound activity log notification bound when its trigger is re-selected', () => {
        const next = setSimpleFilterValue(options, '$activity_log_entry_created', boundToFlag, 'activity-log')

        expect(next.events?.[0].properties).toEqual(boundToFlag.events?.[0].properties)
        expect(next.properties).toEqual(boundToFlag.properties)
    })

    it('drops the previous event filters when a different trigger is chosen', () => {
        const next = setSimpleFilterValue(options, '$early_access_feature_updated', boundToFlag, 'activity-log')

        expect(next.events?.[0]).toEqual({
            id: '$early_access_feature_updated',
            name: 'Early access feature updated',
            type: 'events',
        })
        expect(next.properties).toBeUndefined()
    })

    it('keeps an alert bound to its resource when a different trigger is chosen', () => {
        const boundToAlert: CyclotronJobFiltersType = {
            source: 'internal-events',
            events: [{ id: '$logs_alert_firing', type: 'events' }],
            properties: [
                { key: 'alert_id', type: PropertyFilterType.Event, value: ['7'], operator: PropertyOperator.Exact },
            ],
        }
        const alertOptions = [
            { label: 'Alert firing', value: '$logs_alert_firing' },
            { label: 'Alert resolved', value: '$logs_alert_resolved' },
        ]

        const next = setSimpleFilterValue(alertOptions, '$logs_alert_resolved', boundToAlert, 'logs-alerting')

        expect(next.properties).toEqual(boundToAlert.properties)
    })
})
