import { render, screen, waitFor } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { DataTable } from './DataTable'

// A PersonsNode source has no `displayResponseError` feature, so it takes the DataTable
// branch that shows no backend error text.
const PERSONS_TABLE: DataTableNode = {
    kind: NodeKind.DataTableNode,
    source: { kind: NodeKind.PersonsNode },
} as DataTableNode

describe('DataTable error state', () => {
    it('classifies a failure on a source that cannot show the backend error', async () => {
        useMocks({
            get: { '/api/environments/:team_id/persons/': () => [500, { detail: 'boom' }] },
        })
        initKeaTests()

        render(<DataTable query={PERSONS_TABLE} setQuery={() => {}} />)

        await waitFor(() => {
            expect(screen.getByText("PostHog couldn't complete this query")).toBeTruthy()
        })
    })
})
