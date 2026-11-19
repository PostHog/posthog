import { fireEvent, render, screen } from '@testing-library/react'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { actionsLogic } from '../logics/actionsLogic'
import { ActionsTable } from './ActionsTable'

describe('ActionsTable', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/actions/': { count: 0, results: [] },
            },
        })
        initKeaTests()
        router.actions.push(urls.actions())
        actionsLogic.mount()
    })

    // actionsLogic owns the `ordering` URL param. If LemonTable also writes its own `order` param, its push
    // drops `ordering`, urlToAction restores the previous sort, and the click does nothing.
    it('keeps the sort a header click picks on the URL', () => {
        render(<ActionsTable />)

        fireEvent.click(screen.getByText('Created'))

        expect(router.values.searchParams).toEqual({ ordering: '-created_at' })
        expect(actionsLogic.values.filters.ordering).toEqual('-created_at')
    })
})
