import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { initKeaTests } from '~/test/init'

import { renderColumn } from './renderColumn'
import { defaultDataTableColumns } from './utils'

const select = defaultDataTableColumns(NodeKind.EventsQuery)
const eventsTable = setLatestVersionsOnQuery({
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.EventsQuery, select },
}) as DataTableNode

const personSelect = ['*', 'event', 'person', 'timestamp']
const personColumnTable = setLatestVersionsOnQuery({
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.EventsQuery, select: personSelect },
}) as DataTableNode
const hogqlTable = setLatestVersionsOnQuery({
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.HogQLQuery, query: 'select min(timestamp) from events' },
}) as DataTableNode
const actorsTable = setLatestVersionsOnQuery({
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.ActorsQuery, select: ['person', 'id'] },
}) as DataTableNode

function renderPersonColumnCell(value: Record<string, unknown>, query: DataTableNode = personColumnTable): void {
    render(
        <Provider>
            {renderColumn(
                'person',
                value,
                personSelect.map(() => null),
                0,
                1,
                query
            )}
        </Provider>
    )
}

function renderPersonCell(displayName: string): void {
    render(
        <Provider>
            {renderColumn(
                'person_display_name',
                {
                    id: 'c3b1f6a2-0000-0000-0000-000000000000',
                    distinct_id: 'the-distinct-id',
                    display_name: displayName,
                },
                select.map(() => null),
                0,
                1,
                eventsTable
            )}
        </Provider>
    )
}

describe('renderColumn', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => cleanup())

    it.each([
        ['a person profile supplied the name', 'someone@example.com', 1],
        ['the name fell back to the distinct ID', 'the-distinct-id', 0],
    ])('person_display_name links %s: %s', (_case, displayName, links) => {
        renderPersonCell(displayName)

        expect(screen.getByText(displayName)).toBeInTheDocument()
        expect(screen.queryAllByRole('link')).toHaveLength(links)
    })

    it('opens the person popover even when the name fell back to the distinct ID', async () => {
        // A profile created after the event still answers a lookup by distinct ID, so the popover
        // is the reader's only path to it. Suppressing it strands them on an unlinked cell.
        renderPersonCell('the-distinct-id')
        await userEvent.click(screen.getByText('the-distinct-id'))

        expect(await screen.findByText('No profile associated with this ID')).toBeInTheDocument()
    })

    it.each([
        // A profile with no display properties still serializes `properties`, which is the signal
        ['resolved a profile', { distinct_id: 'the-distinct-id', properties: {} }, 1, 0],
        ['resolved none', { distinct_id: 'the-distinct-id' }, 0, 1],
    ])('person column, query runner %s', async (_case, value, popovers, notices) => {
        renderPersonColumnCell(value as Record<string, unknown>)
        await userEvent.click(screen.getByText('the-distinct-id'))

        await waitFor(() => {
            // PersonPreview mounting is the probe for the popover. It reports no profile either way,
            // because this test leaves the persons API unmocked.
            expect(screen.queryAllByText('No profile associated with this ID')).toHaveLength(popovers as number)
            expect(screen.queryAllByText('This distinct ID has no person profile.')).toHaveLength(notices as number)
        })
    })

    it('renders the actors person column through the core renderer', () => {
        // A product renderer registered under the bare key `person` used to win here and render
        // "Unknown", because it matches on `distinct_id` and an actor carries `distinct_ids`.
        renderPersonColumnCell(
            {
                id: 'c3b1f6a2-0000-0000-0000-000000000000',
                distinct_ids: ['the-distinct-id'],
                properties: { email: 'someone@example.com' },
            },
            actorsTable
        )

        expect(screen.getByText('someone@example.com')).toBeInTheDocument()
        expect(screen.queryByText('Unknown')).toBeNull()
    })

    it.each([
        ['UTC', '1970-01-01T00:00:00Z'],
        ['an offset', '1970-01-01T01:00:00+01:00'],
        ['microseconds', '1970-01-01T00:00:00.000000Z'],
    ])('renders the epoch from a HogQL aggregate over no rows as the raw value, with %s', (_case, value) => {
        render(<Provider>{renderColumn('min(timestamp)', value, [value], 0, 1, hogqlTable)}</Provider>)

        expect(screen.getByText(value)).toBeInTheDocument()
        expect(screen.queryByText(/years ago/)).toBeNull()
    })

    it('renders a sub-millisecond timestamp after the epoch as a time, not as the epoch', () => {
        const value = '1970-01-01T00:00:00.000001Z'
        render(<Provider>{renderColumn('min(timestamp)', value, [value], 0, 1, hogqlTable)}</Provider>)

        expect(screen.queryByText(value)).toBeNull()
    })
})
