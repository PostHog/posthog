import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { EventsQuery } from '~/queries/schema/schema-general'

import { WIDGET_TILE_REFRESH_DEBOUNCE_MS } from '../constants'
import { ActivityEventsWidgetTileFilters } from './ActivityEventsWidgetTileFilters'

jest.mock('products/actions/frontend/components/EventName', () => ({
    EventName: (): JSX.Element => <div>Event name filter</div>,
}))

jest.mock('~/queries/nodes/EventsNode/EventPropertyFilters', () => ({
    EventPropertyFilters: ({ query, setQuery }: { query: EventsQuery; setQuery: (query: EventsQuery) => void }) => (
        <>
            <div>{`Property filters for ${query.event}`}</div>
            <button
                type="button"
                onClick={() =>
                    setQuery({
                        ...query,
                        properties: [
                            { type: 'person', key: 'email', operator: 'icontains', value: '@posthog.com' },
                        ] as EventsQuery['properties'],
                    })
                }
            >
                Add property filter
            </button>
            <button type="button" onClick={() => setQuery({ ...query, properties: [] })}>
                Clear property filters
            </button>
        </>
    ),
}))

describe('ActivityEventsWidgetTileFilters', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('persists added and cleared property filters without dropping existing config', async () => {
        const onUpdateConfig = jest.fn().mockResolvedValue(undefined)

        render(
            <ActivityEventsWidgetTileFilters
                tileId={1}
                config={{ limit: 10, dateRange: { date_from: '-7d' }, eventName: '$pageview' }}
                onUpdateConfig={onUpdateConfig}
            />
        )

        expect(screen.getByText('Property filters for $pageview')).toBeInTheDocument()

        fireEvent.click(screen.getByText('Add property filter'))
        await act(async () => {
            jest.advanceTimersByTime(WIDGET_TILE_REFRESH_DEBOUNCE_MS)
            await Promise.resolve()
        })

        expect(onUpdateConfig).toHaveBeenLastCalledWith({
            limit: 10,
            dateRange: { date_from: '-7d' },
            eventName: '$pageview',
            properties: [
                {
                    type: 'person',
                    key: 'email',
                    operator: 'icontains',
                    value: '@posthog.com',
                },
            ],
        })

        fireEvent.click(screen.getByText('Clear property filters'))
        await act(async () => {
            jest.advanceTimersByTime(WIDGET_TILE_REFRESH_DEBOUNCE_MS)
            await Promise.resolve()
        })

        expect(onUpdateConfig).toHaveBeenLastCalledWith({
            limit: 10,
            dateRange: { date_from: '-7d' },
            eventName: '$pageview',
            properties: [],
        })
    })
})
