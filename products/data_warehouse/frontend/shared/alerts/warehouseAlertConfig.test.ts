import { PlatformAlertConfigurationApi } from 'products/alerts_platform/frontend/generated/api.schemas'

import {
    WarehouseAlertFormValues,
    alertsForScope,
    buildCreateBody,
    buildEditBody,
    formValuesFromAlert,
    newWarehouseAlertForm,
} from './warehouseAlertConfig'

function makeAlert(overrides: Partial<PlatformAlertConfigurationApi> = {}): PlatformAlertConfigurationApi {
    return {
        id: 'alert-1',
        name: 'Warehouse sync failures',
        enabled: true,
        source_kind: 'warehouse_source',
        source_config: { source_ids: [], group_by: 'source', email_project_members: true },
        check_interval_minutes: 5,
        recurrence_unit: null,
        anchor_time: null,
        evaluation_periods: 1,
        datapoints_to_alarm: 1,
        cooldown_minutes: 15,
        schedule_restriction: { blocked_windows: [{ start: '22:00', end: '07:00' }] },
        next_check_at: null,
        consecutive_failures: 0,
        legacy_configuration_id: null,
        grouping: { mode: 'by_result_labels', keys: ['source_id'], max_instances: 50, on_overflow: 'degrade_visible' },
        snooze_until: null,
        check_status: 'ok',
        overflowed_groups: 0,
        overflow_is_lower_bound: false,
        owner: 'platform',
        created_at: '2026-10-01T00:00:00Z',
        updated_at: '2026-10-01T00:00:00Z',
        alerts: [],
        ...overrides,
    }
}

const FORM: WarehouseAlertFormValues = {
    name: '  Stripe failures  ',
    enabled: true,
    targetIds: ['source-a'],
    groupBy: 'schema',
    includeBillingLimits: true,
    emailProjectMembers: false,
}

describe('warehouseAlertConfig', () => {
    // The backend rejects a warehouse alert whose grouping key does not match what it groups on.
    test.each([
        ['warehouse_source', 'schema', ['schema_id']],
        ['warehouse_source', 'source', ['source_id']],
        ['warehouse_destination', 'source', ['destination_id']],
    ] as const)('a %s alert grouped by %s groups on %j', (kind, groupBy, keys) => {
        const body = buildCreateBody(kind, { ...FORM, groupBy })

        expect(body).toMatchObject({
            source_kind: kind,
            name: 'Stripe failures',
            grouping: { mode: 'by_result_labels', keys },
            evaluation_periods: 1,
            datapoints_to_alarm: 1,
        })
    })

    test.each([
        [
            'warehouse_source',
            {
                source_ids: ['source-a'],
                group_by: 'schema',
                include_billing_limits: true,
                email_project_members: false,
            },
        ],
        ['warehouse_destination', { destination_ids: ['source-a'], email_project_members: false }],
    ] as const)('a %s alert sends only the settings its kind accepts', (kind, sourceConfig) => {
        expect(buildCreateBody(kind, FORM).source_config).toEqual(sourceConfig)
    })

    it('keeps the settings the form does not show when it edits an alert', () => {
        const alert = makeAlert()

        expect(buildEditBody(alert, FORM)).toMatchObject({
            schedule_restriction: alert.schedule_restriction,
            cooldown_minutes: 15,
            grouping: { mode: 'by_result_labels', keys: ['schema_id'], max_instances: 50 },
        })
    })

    it('reads the default alert back into the form unchanged', () => {
        const alert = makeAlert()

        expect(buildEditBody(alert, formValuesFromAlert(alert))).toMatchObject({
            name: alert.name,
            source_config: { source_ids: [], group_by: 'source', email_project_members: true },
            grouping: { keys: ['source_id'] },
        })
    })

    it('sends the stored source config back when the form leaves it alone', () => {
        const storedConfig = { source_ids: ['deleted-source'] }
        const alert = makeAlert({ source_config: storedConfig })

        const body = buildEditBody(alert, { ...formValuesFromAlert(alert), name: 'Renamed' })

        expect(body.name).toEqual('Renamed')
        expect(body.source_config).toBe(storedConfig)
    })

    it('starts a new alert on the target it was opened from', () => {
        expect(newWarehouseAlertForm('warehouse_destination', ['destination-a']).targetIds).toEqual(['destination-a'])
    })

    test.each([
        ['every alert of the kind with no target', undefined, ['all', 'scoped', 'other-source']],
        ['alerts that watch every source or this one', 'source-a', ['all', 'scoped']],
        ['only alerts that watch every source for an unwatched source', 'source-c', ['all']],
    ])('lists %s', (_, targetId, expectedIds) => {
        const alerts = [
            makeAlert({ id: 'all' }),
            makeAlert({ id: 'scoped', source_config: { source_ids: ['source-a', 'source-b'] } }),
            makeAlert({ id: 'other-source', source_config: { source_ids: ['source-b'] } }),
            makeAlert({ id: 'logs', source_kind: 'logs', source_config: {} }),
            makeAlert({ id: 'destination', source_kind: 'warehouse_destination', source_config: {} }),
        ]

        expect(alertsForScope(alerts, 'warehouse_source', targetId).map((alert) => alert.id)).toEqual(expectedIds)
    })
})
