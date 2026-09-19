import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { dayjs } from 'lib/dayjs'

import { DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { DataTableVisualization } from '../DataVisualization'

const SIGNED_UP_AT = '2026-09-14T12:00:00Z'

describe('Table row details', () => {
    const query: DataVisualizationNode = {
        kind: NodeKind.DataVisualizationNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query: 'select signed_up_at, email from persons',
        },
        display: ChartDisplayType.ActionsTable,
    }

    const cachedResults: HogQLQueryResponse<any[][]> = {
        results: [[SIGNED_UP_AT, 'someone@example.com']],
        columns: ['signed_up_at', 'email'],
        types: [
            ['signed_up_at', 'DateTime'],
            ['email', 'String'],
        ],
    }

    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows the response value of a datetime column, not the epoch seconds the table sorts on', async () => {
        render(
            <DataTableVisualization
                uniqueKey="data-visualization-row-details"
                query={query}
                setQuery={jest.fn()}
                cachedResults={cachedResults}
                readOnly
            />
        )

        await userEvent.click(await screen.findByLabelText('Show row details'))

        const modal = await waitFor(() => {
            const element = document.querySelector<HTMLElement>('.RowDetailsModal')
            if (!element) {
                throw new Error('Expected the row details modal to open')
            }
            return element
        })

        expect(within(modal).getByText(SIGNED_UP_AT)).not.toBeNull()
        expect(within(modal).queryByText(String(dayjs(SIGNED_UP_AT).unix()))).toBeNull()
        expect(within(modal).getByText('someone@example.com')).not.toBeNull()
    })
})
