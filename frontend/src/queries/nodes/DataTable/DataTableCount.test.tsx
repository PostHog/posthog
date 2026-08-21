import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'
import posthog from 'posthog-js'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { DataTableCount } from '~/queries/nodes/DataTable/DataTableCount'
import * as queryModule from '~/queries/query'
import { ActorsQuery, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

const testKey = 'testDataTableCountKey'

describe('DataTableCount', () => {
    let logic: ReturnType<typeof dataNodeLogic.build>

    // A search term makes hasActiveFilters true, so the count line compares filtered to total.
    const query: ActorsQuery = { kind: NodeKind.ActorsQuery, select: ['id'], search: 'foo' }

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    function renderCount(): void {
        render(
            <BindLogic logic={dataNodeLogic} props={{ key: testKey, query, autoLoad: false }}>
                <DataTableCount />
            </BindLogic>
        )
    }

    // The total count runs as a HogQLQuery; the filtered count keeps the ActorsQuery kind.
    function mockCounts(onFilteredCount: () => any): void {
        jest.spyOn(queryModule, 'performQuery').mockImplementation(async (q: any) => {
            if (q.kind === NodeKind.HogQLQuery) {
                return { results: [[305]] } as any
            }
            return onFilteredCount()
        })
    }

    it('falls back to the total when the filtered count query fails, instead of showing 0 matched', async () => {
        logic = dataNodeLogic({ key: testKey, query, autoLoad: false })
        logic.mount()
        mockCounts(() => {
            throw new Error('count query failed')
        })

        logic.actions.loadTotalCount()
        await waitFor(() => expect(logic.values.totalCount).toBe(305))
        logic.actions.loadFilteredCount()
        await waitFor(() => expect(logic.values.filteredCountLoading).toBe(false))
        expect(logic.values.filteredCount).toBeNull()

        renderCount()

        expect(screen.getByText('Total count: 305 persons')).toBeInTheDocument()
        expect(screen.queryByText(/matched out of/)).not.toBeInTheDocument()
    })

    it('shows the filtered count when it resolves', async () => {
        logic = dataNodeLogic({ key: testKey, query, autoLoad: false })
        logic.mount()
        mockCounts(() => ({ results: [[12]] }))

        logic.actions.loadTotalCount()
        await waitFor(() => expect(logic.values.totalCount).toBe(305))
        logic.actions.loadFilteredCount()
        await waitFor(() => expect(logic.values.filteredCount).toBe(12))

        renderCount()

        expect(screen.getByText('12 persons matched out of 305')).toBeInTheDocument()
    })
})
