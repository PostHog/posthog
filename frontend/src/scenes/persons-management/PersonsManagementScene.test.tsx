import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { router } from 'kea-router'
import { MOCK_TEAM_ID } from 'lib/api.mock'
import { PersonsManagementScene } from 'scenes/persons-management/PersonsManagementScene'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

const testExampleResult = [
    {
        id: 1,
        name: 'Test User',
        distinct_ids: ['test_id'],
        properties: {
            email: 'test@example.com',
        },
        created_at: '2021-01-01T00:00:00Z',
    },
]

describe('PersonsManagementScene', () => {
    afterEach(() => {
        cleanup()
    })

    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query': async (req, res, ctx) => {
                    const payload = await req.json()
                    if (payload.query.search) {
                        if (payload.query.search !== 'test@example.com') {
                            return res(
                                ctx.json({
                                    results: [],
                                    count: 0,
                                    complete: true,
                                })
                            )
                        }
                        return res(
                            ctx.json({
                                results: [testExampleResult],
                                count: 1,
                                complete: true,
                            })
                        )
                    }
                    // if (payload.query.kind !== 'ActorsQuery') {
                    //     return res(ctx.json({
                    //         results: [], count: 0,
                    //         complete: true,
                    //     }))
                    // }
                    // by default we have more than one actor

                    return res(
                        ctx.json({
                            results: [
                                testExampleResult,
                                [
                                    {
                                        id: 2,
                                        name: 'And another test User',
                                        distinct_ids: ['test_i2'],
                                        properties: {
                                            email: 'test2@example.com',
                                        },
                                        created_at: '2021-01-01T00:00:00Z',
                                    },
                                ],
                            ],
                            count: 1,
                            complete: true,
                        })
                    )
                },
            },
        })
        initKeaTests()
        router.actions.push(urls.persons())
    })

    it('can search for persons', async () => {
        render(
            <Provider>
                <PersonsManagementScene />
            </Provider>
        )

        const searchInput = screen.getByPlaceholderText('Search for persons')
        userEvent.type(searchInput, 'test@example.com')

        const lemonTable = screen.getByTestId('persons-table')
        const withinTable = within(lemonTable)

        await waitFor(() => {
            expect(
                withinTable.getByTitle('This is the Gravatar for test@example.com <test@example.com>')
            ).toBeInTheDocument()
            expect(withinTable.getByText('T', { selector: '.Lettermark' })).toBeInTheDocument()
        })
    })

    it('can get the empty state for persons', async () => {
        render(
            <Provider>
                <PersonsManagementScene />
            </Provider>
        )

        const searchInput = screen.getByPlaceholderText('Search for persons')
        userEvent.type(searchInput, 'not-in-mock@example.com')

        const lemonTable = screen.getByTestId('persons-table')
        const withinTable = within(lemonTable)

        await waitFor(() => {
            expect(withinTable.getByText('There are no matching persons for this query')).toBeInTheDocument()
        })
    })

    it('can navigate to the person', async () => {
        render(
            <Provider>
                <PersonsManagementScene />
            </Provider>
        )

        // Wait for loading to complete
        await waitFor(() => {
            const table = screen.getByTestId('persons-table')
            expect(table).not.toHaveClass('LemonTable--loading')
        })

        // want to click on data-attr="persons-table" tr .PersonDisplay Link first one
        const lemonTable = screen.getByTestId('persons-table')
        const tableBody = lemonTable.querySelector('tbody')
        const withinTable = within(tableBody!)
        // there should be two rows, and i only care about the first one
        const rows = withinTable.getAllByRole('row')
        expect(rows).toHaveLength(2)
        const firstRow = rows[0]
        const personDisplayLink = within(firstRow).getByRole('link')

        userEvent.click(personDisplayLink)

        await waitFor(() => {
            expect(router.values.location.pathname).toBe(`/project/${MOCK_TEAM_ID}/person/test_id`)
        })
    })
})
