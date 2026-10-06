import { expectLogic } from 'kea-test-utils'

import * as api from '~/generated/core/api'
import { EnterprisePropertyDefinitionApi } from '~/generated/core/api.schemas'
import { BIField } from '~/queries/schema/schema-business-intelligence'
import { initKeaTests } from '~/test/init'

import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'
import { getBIPropertyTarget } from './biPropertyFields'
import { biPropertyFieldsLogic } from './biPropertyFieldsLogic'

const field: BIField = {
    id: 'events:person.properties',
    name: 'person.properties',
    expression: 'person.properties',
    type: 'unknown',
    source: { table: 'events' },
}
const definition = (
    name: string,
    property_type: EnterprisePropertyDefinitionApi['property_type'] = 'String'
): EnterprisePropertyDefinitionApi => ({ name, property_type }) as EnterprisePropertyDefinitionApi

describe('BI related properties', () => {
    beforeEach(() => initKeaTests())

    it('loads related properties on expansion, pages, searches, and keeps the root table in generated SQL', async () => {
        const list = jest
            .spyOn(api, 'propertyDefinitionsList')
            .mockResolvedValue({ count: 2, results: [definition('profile.country')] })
        const logic = biPropertyFieldsLogic({ tabId: 'properties', field })
        logic.mount()
        try {
            expect(list).not.toHaveBeenCalled()
            await expectLogic(logic, () => logic.actions.toggleExpanded()).toFinishAllListeners()
            expect(list).toHaveBeenCalledWith(
                '997',
                expect.objectContaining({ type: 'person', exclude_hidden: true, exclude_restricted: true, offset: 0 })
            )
            expect(logic.values.fields[0]).toMatchObject({
                expression: 'person.properties."profile.country"',
                source: field.source,
                type: 'string',
            })
            list.mockResolvedValue({ count: 2, results: [definition('annual_spend', 'Numeric')] })
            await expectLogic(logic, () => logic.actions.loadPage({ offset: 1 })).toFinishAllListeners()
            expect(logic.values.fields).toHaveLength(2)
            const query = buildBIQuery({
                ...DEFAULT_BI_CONFIG,
                source: field.source,
                rows: [logic.values.fields[0]],
                values: [{ field: logic.values.fields[1], aggregation: 'sum' }],
            })!.query
            expect(query).toContain('person.properties."profile.country"')
            expect(query).toContain('sum(person.properties.annual_spend)')
            expect(query).toContain('FROM events')
            await expectLogic(logic, () => logic.actions.setSearch('annual')).toFinishAllListeners()
            expect(list).toHaveBeenLastCalledWith('997', expect.objectContaining({ search: 'annual', offset: 0 }))
            expect(logic.values.fields).toHaveLength(1)
        } finally {
            logic.unmount()
            list.mockRestore()
        }
    })

    it('recovers from failed property loading without caching the failure', async () => {
        const list = jest.spyOn(api, 'propertyDefinitionsList').mockRejectedValue(new Error('Unavailable'))
        const logic = biPropertyFieldsLogic({ tabId: 'retry', field })
        logic.mount()
        try {
            await expectLogic(logic, () => logic.actions.toggleExpanded()).toFinishAllListeners()
            expect(logic.values.error).toBe('Unavailable')
            expect(logic.values.pageLoading).toBe(false)
            list.mockResolvedValue({ count: 0, results: [] })
            await expectLogic(logic, () => logic.actions.loadPage({ offset: 0 })).toFinishAllListeners()
            expect(logic.values.error).toBeNull()
            expect(logic.values.page).toEqual({ count: 0, results: [] })
        } finally {
            logic.unmount()
            list.mockRestore()
        }
    })

    it.each([
        [{ ...field, name: 'properties', type: 'json' as const }, { type: 'event' }],
        [field, { type: 'person' }],
        [
            { ...field, name: 'group_0.properties' },
            { type: 'group', groupTypeIndex: 0 },
        ],
        [{ ...field, source: { table: 'stripe_charges' } }, null],
        [{ ...field, source: { table: 'events', connectionId: 'external' } }, null],
    ])('selects property definitions for %j', (input, expected) => {
        expect(getBIPropertyTarget(input as BIField)).toEqual(expected)
    })
})
