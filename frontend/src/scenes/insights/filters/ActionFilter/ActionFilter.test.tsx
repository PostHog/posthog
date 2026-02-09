import '@testing-library/jest-dom'
import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { FilterType } from '~/types'

import { ActionFilter } from './ActionFilter'
import filtersJson from './__mocks__/filters.json'
import { entityFilterLogic } from './entityFilterLogic'

jest.mock('lib/components/AutoSizer', () => ({
    AutoSizer: ({ renderProp }: { renderProp: (size: { height: number; width: number }) => React.ReactNode }) =>
        renderProp({ height: 400, width: 400 }),
}))

describe('ActionFilter', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/actions/': { results: [] },
                '/api/projects/:team/event_definitions/': { results: [], count: 0 },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('does not call setLocalFilters when re-rendered with same filter values', () => {
        const filters = filtersJson as FilterType
        const setFilters = jest.fn()

        const { rerender } = render(
            <Provider>
                <ActionFilter filters={{ ...filters }} setFilters={setFilters} typeKey="test-rerender" />
            </Provider>
        )

        expect(screen.getByTestId('trend-element-subject-0')).toBeInTheDocument()

        const logic = entityFilterLogic({ setFilters, filters, typeKey: 'test-rerender' })
        const setLocalFiltersSpy = jest.spyOn(logic.actions, 'setLocalFilters')

        rerender(
            <Provider>
                <ActionFilter filters={{ ...filters }} setFilters={setFilters} typeKey="test-rerender" />
            </Provider>
        )

        expect(setLocalFiltersSpy).not.toHaveBeenCalled()
    })
})
