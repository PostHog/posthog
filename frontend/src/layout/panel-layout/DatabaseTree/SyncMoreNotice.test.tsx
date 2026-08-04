import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { queryDatabaseLogic } from 'scenes/data-warehouse/editor/sidebar/queryDatabaseLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { SyncMoreNotice } from './SyncMoreNotice'

describe('SyncMoreNotice', () => {
    let logic: ReturnType<typeof queryDatabaseLogic.build>

    beforeEach(() => {
        initKeaTests()
        teamLogic.mount()
        logic = queryDatabaseLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        cleanup()
    })

    it('renders the empty-state banner when there are no non-PostHog sources', () => {
        databaseTableListLogic.findMounted()?.actions.loadDatabaseSuccess({ tables: {}, joins: [] })

        render(<SyncMoreNotice />)

        expect(screen.getByText('No data warehouse sources connected')).toBeInTheDocument()
    })

    it.each([
        [
            'a non-PostHog source is connected',
            () =>
                databaseTableListLogic.findMounted()?.actions.loadDatabaseSuccess({
                    tables: {
                        stripe_customers: {
                            type: 'data_warehouse',
                            id: 'table-1',
                            name: 'stripe_customers',
                            fields: {},
                        },
                    },
                    joins: [],
                }),
        ],
        [
            'the notice has been dismissed',
            () => {
                databaseTableListLogic.findMounted()?.actions.loadDatabaseSuccess({ tables: {}, joins: [] })
                logic.actions.setSyncMoreNoticeDismissed(true)
            },
        ],
        ['the database is still loading', () => databaseTableListLogic.findMounted()?.actions.loadDatabase()],
        [
            // Regression: the banner used to ignore a failed schema load and tell users "no sources connected"
            // right next to the sidebar's own "couldn't load your schema" retry node.
            'the schema failed to load',
            () => databaseTableListLogic.findMounted()?.actions.loadDatabaseFailure('A server error occurred.'),
        ],
    ])('renders nothing when %s', (_, setup) => {
        setup()

        const { container } = render(<SyncMoreNotice />)

        expect(screen.queryByText('No data warehouse sources connected')).not.toBeInTheDocument()
        expect(container).toBeEmptyDOMElement()
    })
})
