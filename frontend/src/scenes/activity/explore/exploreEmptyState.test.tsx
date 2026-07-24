import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { DataTableNode, EventsQuery } from '~/queries/schema/schema-general'

import { getDefaultEventsSceneQuery, getDefaultSessionsSceneQuery } from './defaults'
import { getExploreEmptyStateContext } from './exploreEmptyState'

describe('getExploreEmptyStateContext', () => {
    test.each([
        ['events', getDefaultEventsSceneQuery],
        ['sessions', getDefaultSessionsSceneQuery],
    ] as const)('offers a widen affordance for the narrow %s default window', (_, getQuery) => {
        const context = getExploreEmptyStateContext(getQuery(), jest.fn())
        expect(context.emptyStateHeading).toContain('in the last hour')
        expect(context.emptyStateDetail).toBeTruthy()
    })

    it('shows the generic empty state once the window has been widened', () => {
        const widened: DataTableNode = {
            ...getDefaultEventsSceneQuery(),
            source: { ...getDefaultEventsSceneQuery().source, after: '-7d' } as EventsQuery,
        }
        expect(getExploreEmptyStateContext(widened, jest.fn())).toEqual({})
    })

    it('widens the query to the last 24 hours when the affordance is clicked', async () => {
        const setQuery = jest.fn()
        const context = getExploreEmptyStateContext(getDefaultEventsSceneQuery(), setQuery)

        render(<>{context.emptyStateDetail}</>)
        await userEvent.click(screen.getByRole('button', { name: 'Show last 24 hours' }))

        expect(setQuery).toHaveBeenCalledWith(
            expect.objectContaining({ source: expect.objectContaining({ after: '-24h' }) })
        )
    })
})
