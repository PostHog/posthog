import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import { WidenTimeRangeSuggestion } from './WidenTimeRangeSuggestion'

const baseEventsTable = (after: string | undefined): DataTableNode => ({
    kind: NodeKind.DataTableNode,
    full: true,
    source: {
        kind: NodeKind.EventsQuery,
        select: ['*', 'event', 'timestamp'],
        orderBy: ['timestamp DESC'],
        ...(after !== undefined ? { after } : {}),
    },
})

describe('WidenTimeRangeSuggestion', () => {
    afterEach(() => cleanup())

    it('renders a "Try last 24 hours" button when an EventsQuery uses the default -1h window', () => {
        const setQuery = jest.fn()

        render(<WidenTimeRangeSuggestion query={baseEventsTable('-1h')} setQuery={setQuery} />)

        const button = screen.getByRole('button', { name: /Try last 24 hours/i })
        fireEvent.click(button)

        expect(setQuery).toHaveBeenCalledTimes(1)
        expect(setQuery).toHaveBeenCalledWith(
            expect.objectContaining({
                source: expect.objectContaining({ after: '-24h' }),
            })
        )
    })

    it('also covers shorter sparse windows like -30m and -15m', () => {
        const setQuery = jest.fn()

        const { rerender } = render(<WidenTimeRangeSuggestion query={baseEventsTable('-30m')} setQuery={setQuery} />)
        expect(screen.getByRole('button', { name: /Try last 24 hours/i })).toBeTruthy()

        rerender(<WidenTimeRangeSuggestion query={baseEventsTable('-15m')} setQuery={setQuery} />)
        expect(screen.getByRole('button', { name: /Try last 24 hours/i })).toBeTruthy()
    })

    it('renders nothing when the EventsQuery already uses a wider window', () => {
        const setQuery = jest.fn()

        const { container } = render(<WidenTimeRangeSuggestion query={baseEventsTable('-24h')} setQuery={setQuery} />)

        expect(container.firstChild).toBeNull()
        expect(screen.queryByRole('button')).toBeNull()
    })

    it('renders nothing when the source is not an EventsQuery', () => {
        const setQuery = jest.fn()
        const nonEventsQuery: DataTableNode = {
            kind: NodeKind.DataTableNode,
            source: {
                kind: NodeKind.PersonsNode,
            },
        } as unknown as DataTableNode

        const { container } = render(<WidenTimeRangeSuggestion query={nonEventsQuery} setQuery={setQuery} />)

        expect(container.firstChild).toBeNull()
    })

    it('preserves other query fields when widening the range', () => {
        const setQuery = jest.fn()
        const query: DataTableNode = {
            ...baseEventsTable('-1h'),
            source: {
                kind: NodeKind.EventsQuery,
                select: ['*', 'event', 'timestamp'],
                orderBy: ['timestamp DESC'],
                after: '-1h',
                event: '$pageview',
                limit: 50,
            },
        }

        render(<WidenTimeRangeSuggestion query={query} setQuery={setQuery} />)
        fireEvent.click(screen.getByRole('button', { name: /Try last 24 hours/i }))

        expect(setQuery).toHaveBeenCalledWith({
            ...query,
            source: {
                ...query.source,
                after: '-24h',
            },
        })
    })
})
