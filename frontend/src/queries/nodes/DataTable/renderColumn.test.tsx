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

describe('renderColumn', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => cleanup())

    it.each([
        ['full', true],
        ['force_upgrade', true],
        ['propertyless', false],
    ])('links the person column of a %s event: %s', (personMode, linked) => {
        const value = {
            id: 'c3b1f6a2-0000-0000-0000-000000000000',
            distinct_id: 'the-distinct-id',
            display_name: 'the-distinct-id',
            person_mode: personMode,
        }

        render(
            <Provider>
                {renderColumn(
                    'person_display_name',
                    value,
                    select.map(() => null),
                    0,
                    1,
                    eventsTable
                )}
            </Provider>
        )

        expect(screen.getByText('the-distinct-id')).toBeInTheDocument()
        expect(screen.queryAllByRole('link')).toHaveLength(linked ? 1 : 0)
    })

    it('opens no profile popover for a personless event', async () => {
        const value = {
            id: 'c3b1f6a2-0000-0000-0000-000000000000',
            distinct_id: 'the-distinct-id',
            display_name: 'the-distinct-id',
            person_mode: 'propertyless',
        }

        render(
            <Provider>
                {renderColumn(
                    'person_display_name',
                    value,
                    select.map(() => null),
                    0,
                    1,
                    eventsTable
                )}
            </Provider>
        )
        await userEvent.click(screen.getByText('the-distinct-id'))

        expect(screen.queryByText('No profile associated with this ID')).toBeNull()
    })
})
