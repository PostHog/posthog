import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { DatabaseSchemaTable } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { biSourceContextLogic } from './biSourceContextLogic'
import { biSourceMetadataLogic } from './biSourceMetadataLogic'

const table: DatabaseSchemaTable = { id: 'table-example', name: 'purchases', type: 'data_warehouse', fields: {} }
beforeEach(() => initKeaTests())

it('loads all annotation pages and keeps check health independent of certification', async () => {
    const offsets: string[] = []
    useMocks({
        get: {
            '/api/projects/:team_id/warehouse_column_annotations/': ({ request }) => {
                const offset = new URL(request.url).searchParams.get('offset')!
                offsets.push(offset)
                return offset === '0'
                    ? { results: [{ column_name: '', description: 'Completed purchases' }], next: 'next' }
                    : { results: [{ column_name: 'amount', description: 'Amount in cents' }], next: null }
            },
            '/api/projects/:team_id/data_quality_checks/health/': [
                {
                    subject_type: 'table',
                    subject_uuid: table.id,
                    health: 'failing',
                    checks_total: 2,
                    checks_failing: 1,
                },
            ],
        },
    })
    const logic = biSourceMetadataLogic({ table })
    await expectLogic(logic, () => {
        logic.mount()
        logic.actions.loadHealth()
    }).toFinishAllListeners()
    expect(offsets).toEqual(['0', '1'])
    expect(logic.values.annotations).toEqual({ '': 'Completed purchases', amount: 'Amount in cents' })
    expect(logic.values.health?.health).toBe('failing')
    logic.unmount()
})

it('resolves native table identity before asking for health and isolates table metadata', async () => {
    const requestedIds: string[] = []
    useMocks({
        get: {
            '/api/projects/:team_id/data_quality_checks/subjects/': [
                { name: 'events', id: 'native-event-id', subject_type: 'posthog_table' },
            ],
            '/api/projects/:team_id/data_quality_checks/health/': ({ request }) => {
                requestedIds.push(new URL(request.url).searchParams.get('subject_uuid')!)
                return []
            },
            '/api/projects/:team_id/warehouse_column_annotations/': {
                results: [{ column_name: 'amount', description: 'Only on purchases' }],
                next: null,
            },
        },
    })
    const source = biSourceMetadataLogic({ table })
    await expectLogic(source, () => {
        source.mount()
        source.actions.loadHealth()
    }).toFinishAllListeners()
    const native = biSourceMetadataLogic({ table: { ...table, id: 'events', name: 'events', type: 'posthog' } })
    await expectLogic(native, () => {
        native.mount()
        native.actions.loadHealth()
    }).toFinishAllListeners()
    expect(requestedIds).toEqual([table.id, 'native-event-id'])
    expect(native.values.annotations).toEqual({})
    expect(native.values.health).toMatchObject({ checks_total: 0, health: 'unknown' })
    expect(source.values.annotations.amount).toBe('Only on purchases')
    source.unmount()
    native.unmount()
})

it('does not turn failed requests into healthy or unchecked sources and retries', async () => {
    let fail = true
    useMocks({
        get: {
            '/api/projects/:team_id/warehouse_column_annotations/': { results: [], next: null },
            '/api/projects/:team_id/data_quality_checks/health/': () => (fail ? [403, { detail: 'Unavailable' }] : []),
        },
    })
    const logic = biSourceMetadataLogic({ table })
    await expectLogic(logic, () => {
        logic.mount()
        logic.actions.loadHealth()
    }).toFinishAllListeners()
    expect(logic.values.healthError).toBe(true)
    expect(logic.values.health).toBeNull()
    fail = false
    await expectLogic(logic, () => logic.actions.loadHealth()).toFinishAllListeners()
    expect(logic.values.healthError).toBe(false)
    expect(logic.values.health?.checks_total).toBe(0)
    logic.unmount()
})

it('keeps prototype-like column names safe before and after annotation loading', async () => {
    useMocks({
        get: {
            '/api/projects/:team_id/warehouse_column_annotations/': {
                results: [
                    { column_name: 'constructor', description: 'Assembly method' },
                    { column_name: '__proto__', description: 'A literal source column' },
                ],
                next: null,
            },
        },
    })
    const logic = biSourceMetadataLogic({ table })
    logic.mount()
    expect(logic.values.annotations.constructor).toBeUndefined()
    expect(logic.values.annotations.__proto__).toBeUndefined()
    await expectLogic(logic).toFinishAllListeners()
    expect(logic.values.annotations.constructor).toBe('Assembly method')
    expect(logic.values.annotations.__proto__).toBe('A literal source column')
    expect(logic.values.annotations.toString).toBeUndefined()
    logic.unmount()
})

it('loads health only when the source-details consumer mounts', async () => {
    const health = jest.fn(() => [])
    useMocks({
        get: {
            '/api/projects/:team_id/warehouse_column_annotations/': { results: [], next: null },
            '/api/projects/:team_id/data_quality_checks/health/': health,
            '/api/projects/:team_id/data_catalog/relationship_proposals/': { results: [], next: null },
        },
    })
    const fields = biSourceMetadataLogic({ table })
    await expectLogic(fields, () => {
        fields.mount()
    }).toFinishAllListeners()
    expect(health).not.toHaveBeenCalled()
    const context = biSourceContextLogic({ table })
    await expectLogic(context, () => {
        context.mount()
    }).toFinishAllListeners()
    await expectLogic(fields).toFinishAllListeners()
    expect(health).toHaveBeenCalledTimes(1)
    context.unmount()
    fields.unmount()
})
