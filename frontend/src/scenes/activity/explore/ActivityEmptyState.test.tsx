import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import { ActivityEmptyStateDetail, widerWindows } from './ActivityEmptyState'

const buildQuery = (after?: string): DataTableNode =>
    ({
        kind: NodeKind.DataTableNode,
        source: { kind: NodeKind.EventsQuery, select: [], ...(after ? { after } : {}) },
    }) as DataTableNode

describe('ActivityEmptyState', () => {
    afterEach(() => cleanup())

    describe('widerWindows', () => {
        test.each([
            ['-1h', ['-24h', '-7d', '-30d']],
            ['-24h', ['-7d', '-30d']],
            ['-7d', ['-30d']],
            ['-30d', []],
        ] as const)('from %s only offers strictly wider windows', (after, expected) => {
            expect(widerWindows(after).map((w) => w.after)).toEqual(expected)
        })

        it('offers nothing when no time window is applied', () => {
            expect(widerWindows(undefined)).toEqual([])
        })
    })

    it('surfaces the active window and expands it on click', () => {
        const setQuery = jest.fn()
        render(<ActivityEmptyStateDetail query={buildQuery('-1h')} setQuery={setQuery} noun="events" />)

        expect(screen.getByText(/last 1 hour/)).toBeInTheDocument()

        fireEvent.click(screen.getByText('Last 7 days'))
        expect(setQuery).toHaveBeenCalledWith(expect.objectContaining({ source: expect.objectContaining({ after: '-7d' }) }))
    })
})
