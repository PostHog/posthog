import { NodeKind } from '~/queries/schema/schema-general'

import { getZendeskTicketsQuery } from './NotebookNodeZendeskTickets'

describe('NotebookNodeZendeskTickets', () => {
    it('does not build a query without a person or group target', () => {
        expect(getZendeskTicketsQuery({})).toBeNull()
    })

    it('builds a person tickets query when personId is provided', () => {
        const query = getZendeskTicketsQuery({ personId: 'person-uuid' })

        expect(query?.kind).toEqual(NodeKind.DataTableNode)
        expect(query?.source.kind).toEqual(NodeKind.HogQLQuery)
    })

    it('builds a group tickets query when groupKey is provided', () => {
        const query = getZendeskTicketsQuery({ groupKey: 'group-key' })

        expect(query?.kind).toEqual(NodeKind.DataTableNode)
        expect(query?.source.kind).toEqual(NodeKind.HogQLQuery)
    })
})
