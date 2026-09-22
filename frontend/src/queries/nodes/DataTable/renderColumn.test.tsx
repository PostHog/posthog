import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
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
})
