import { DWH_SOURCE_TABLE_PROPERTY, HogFlow, WAREHOUSE_VIEW_ROW_EVENT } from '~/cdp/schema/hogflow'
import { HogFunctionInvocationGlobals } from '~/cdp/types'
import { parseJSON } from '~/common/utils/json-parse'
import * as request from '~/common/utils/request'

import { WarehouseTriggerAccess } from './warehouse-trigger-access'

const flow = { id: 'flow-1', trigger: { type: 'data-warehouse-view', table_name: 'daily_totals' } } as HogFlow
const globals = {
    project: { id: 1, name: 'Test project', url: '' },
    event: {
        event: WAREHOUSE_VIEW_ROW_EVENT,
        properties: { [DWH_SOURCE_TABLE_PROPERTY]: 'daily_totals' },
        uuid: 'test-event',
        distinct_id: '',
        timestamp: '',
        elements_chain: '',
        url: '',
    },
} satisfies HogFunctionInvocationGlobals

describe('WarehouseTriggerAccess', () => {
    const config = { INTERNAL_API_BASE_URL: 'http://localhost:8000', WORKFLOW_WAREHOUSE_ACCESS_JWT_SECRET: 'test-key' }
    let fetchSpy: jest.SpyInstance

    beforeEach(() => {
        fetchSpy = jest.spyOn(request, 'internalFetch')
    })

    afterEach(() => jest.restoreAllMocks())

    function respond(allowedIds: string[]): void {
        fetchSpy.mockResolvedValue({ status: 200, json: () => Promise.resolve({ allowed_flow_ids: allowedIds }) })
    }

    it('checks each source once per batch and observes revocations in the next batch', async () => {
        const access = new WarehouseTriggerAccess(config)
        respond([flow.id])
        const allowed = await access.forBatch([globals, globals], { 1: [flow] })
        expect(allowed(flow, globals)).toBe(true)
        expect(fetchSpy).toHaveBeenCalledTimes(1)
        respond([])
        const revoked = await access.forBatch([globals], { 1: [flow] })
        expect(revoked(flow, globals)).toBe(false)
        expect(fetchSpy).toHaveBeenCalledTimes(2)
    })

    it('authorizes the event source even when the workflow has no table filter', async () => {
        respond([])
        const unfiltered = { ...flow, trigger: { type: 'data-warehouse-view' } } as HogFlow
        const allowed = await new WarehouseTriggerAccess(config).forBatch([globals], { 1: [unfiltered] })
        expect(allowed(unfiltered, globals)).toBe(false)
        expect(parseJSON(fetchSpy.mock.calls[0][1].body)).toEqual({
            flow_ids: [flow.id],
            table_name: 'daily_totals',
            trigger_type: 'data-warehouse-view',
        })
    })

    it.each([
        ['unavailable', { status: 503, dump: async () => {} }],
        ['malformed', { status: 200, json: () => Promise.resolve({ allowed_flow_ids: 'all' }) }],
        ['unexpected flow', { status: 200, json: () => Promise.resolve({ allowed_flow_ids: ['other-flow'] }) }],
    ])('refuses the batch when authorization is %s', async (_name, response) => {
        fetchSpy.mockResolvedValue(response)
        await expect(new WarehouseTriggerAccess(config).forBatch([globals], { 1: [flow] })).rejects.toThrow()
    })

    it('refuses warehouse delivery when the signing key is not configured', async () => {
        const access = new WarehouseTriggerAccess({ ...config, WORKFLOW_WAREHOUSE_ACCESS_JWT_SECRET: '' })
        await expect(access.forBatch([globals], { 1: [flow] })).rejects.toThrow('no signing key')
        expect(fetchSpy).not.toHaveBeenCalled()
    })

    it('rejects missing source names and keeps other event types off warehouse triggers', async () => {
        const missingName = { ...globals, event: { ...globals.event!, properties: {} } }
        const pageview = { ...globals, event: { ...globals.event!, event: '$pageview' } }
        const allowed = await new WarehouseTriggerAccess(config).forBatch([missingName, pageview], { 1: [flow] })
        expect(allowed(flow, missingName)).toBe(false)
        expect(allowed(flow, pageview)).toBe(false)
        expect(fetchSpy).not.toHaveBeenCalled()
    })
})
