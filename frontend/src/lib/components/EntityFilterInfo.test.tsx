import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { dayjs } from 'lib/dayjs'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { ActionFilter, EntityFilter, EntityTypes } from '~/types'

import { EntityFilterInfo } from './EntityFilterInfo'

describe('EntityFilterInfo', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/event_definitions/': ({ request }) => {
                    const names = new URL(request.url).searchParams.getAll('names')
                    const results = [
                        { id: '1', name: 'user signed up', last_seen_at: dayjs().subtract(90, 'day').toISOString() },
                    ].filter((definition) => names.includes(definition.name))
                    return [200, { count: results.length, results }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    // A series can be renamed via `custom_name`, or via `name` (e.g. set through the API).
    // In both cases the label alone doesn't reveal the event actually queried, so the
    // underlying event must be shown alongside it.
    it.each([
        [
            'custom_name matching name',
            { type: EntityTypes.EVENTS, id: 'user signed up', name: 'Signed up', custom_name: 'Signed up' },
            'Signed up',
            'user signed up',
        ],
        [
            'name only',
            { type: EntityTypes.EVENTS, id: '$pageview', name: 'Visited posthog.com' },
            'Visited posthog.com',
            'Pageview',
        ],
        [
            'custom_name on an action',
            { type: EntityTypes.ACTIONS, id: 5, name: 'Completed purchase', custom_name: 'Checkout' },
            'Checkout',
            'Completed purchase',
        ],
        [
            'custom_name on an all-events series',
            { type: EntityTypes.EVENTS, id: null, name: 'All events', custom_name: 'Total traffic' },
            'Total traffic',
            'All events',
        ],
    ] as [string, EntityFilter | ActionFilter, string, string][])(
        'shows the underlying entity next to a series renamed via %s',
        (_, filter, label, underlying) => {
            render(<EntityFilterInfo filter={filter} />)
            expect(screen.getByText(label)).toBeInTheDocument()
            expect(screen.getByText(underlying)).toBeInTheDocument()
        }
    )

    it.each([
        [
            'a custom event',
            { type: EntityTypes.EVENTS, id: 'user signed up', name: 'user signed up' },
            'user signed up',
        ],
        ['a core event', { type: EntityTypes.EVENTS, id: '$pageview', name: '$pageview' }, 'Pageview'],
        // API-created series often carry no name at all — the raw id label is not a rename
        ['a name-less core event', { type: EntityTypes.EVENTS, id: '$pageview' }, '$pageview'],
        ['an all-events series', { type: EntityTypes.EVENTS, id: null, name: 'All events' }, 'All events'],
    ] as [string, EntityFilter, string][])('shows a single label for an unrenamed series on %s', (_, filter, label) => {
        const { container } = render(<EntityFilterInfo filter={filter} />)
        expect(screen.getAllByText(label)).toHaveLength(1)
        expect(container.querySelectorAll('.EntityFilterInfo')).toHaveLength(1)
    })

    it('keeps the underlying entity out of the inline label when showSingleName is set', () => {
        const { container } = render(
            <EntityFilterInfo
                filter={{ type: EntityTypes.EVENTS, id: 'user signed up', name: 'Signed up', custom_name: 'Signed up' }}
                showSingleName
            />
        )
        expect(container).toHaveTextContent('Signed up')
        expect(container).not.toHaveTextContent('user signed up')
    })

    it('reveals the raw event key in the tooltip of a renamed series', async () => {
        render(
            <EntityFilterInfo
                filter={{ type: EntityTypes.EVENTS, id: 'user signed up', name: 'Signed up', custom_name: 'Signed up' }}
            />
        )
        userEvent.hover(screen.getByText('Signed up'))
        expect(await screen.findByText(/Event sent as/, {}, { timeout: 3000 })).toBeInTheDocument()
    })

    // A series pointing at an event that stopped arriving charts a flat zero, which reads as a real
    // zero. An action series names an action, not an event, so asking about it draws a bogus tag.
    it('tags only the series whose event PostHog has no fresh data for', async () => {
        render(
            <>
                <EntityFilterInfo
                    filter={{ type: EntityTypes.EVENTS, id: 'user signed up', name: 'user signed up' }}
                    showEventHealth
                />
                <EntityFilterInfo
                    filter={{ type: EntityTypes.ACTIONS, id: 5, name: 'Completed purchase' }}
                    showEventHealth
                />
            </>
        )
        expect(await screen.findByLabelText('Stale')).toBeInTheDocument()
        expect(screen.queryByLabelText('Not seen')).not.toBeInTheDocument()
    })

    // Formula series carry `action: null`, so callers pass a null filter. That must render
    // nothing rather than crash the scene (getUnderlyingEntity used to dereference filter.type).
    it.each([
        ['null', null],
        ['undefined', undefined],
    ] as [string, EntityFilter | ActionFilter | null | undefined][])(
        'renders nothing without throwing for a %s filter',
        (_, filter) => {
            const { container } = render(<EntityFilterInfo filter={filter} />)
            expect(container.querySelectorAll('.EntityFilterInfo')).toHaveLength(0)
        }
    )
})
