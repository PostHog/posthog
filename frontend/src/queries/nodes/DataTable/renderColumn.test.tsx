import { PersonDisplayProps } from 'scenes/persons/PersonDisplay'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'

import { renderColumn } from './renderColumn'
import { defaultDataTableColumns } from './utils'

const select = defaultDataTableColumns(NodeKind.EventsQuery)
const eventsTable = setLatestVersionsOnQuery({
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.EventsQuery, select },
}) as DataTableNode

const TIMESTAMP = '2026-09-07T09:00:00Z'

function personColumnProps(key: string, value: unknown): PersonDisplayProps {
    const row = select.map((column) => (column === '*' ? { timestamp: TIMESTAMP } : null))
    const element = renderColumn(key, value, row, 0, 1, eventsTable)
    return (element as JSX.Element).props
}

describe('renderColumn', () => {
    it('passes the row timestamp to the person column, so its popover links to events around that event', () => {
        const value = { distinct_id: 'the-distinct-id', display_name: 'the-distinct-id' }

        expect(personColumnProps('person_display_name -- Person', value).eventTimestamp).toBe(TIMESTAMP)
    })
})
