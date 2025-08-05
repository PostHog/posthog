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
        display_name: 'test@example.com',
        id: '0257ab53-0816-55da-8919-73abbf36d5a9',
    },
    '0257ab53-0816-55da-8919-73abbf36d5a9',
    '2025-02-04T22:34:07.384000Z',
    1,
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
                                        display_name: 'test2@example.com',
                                        id: 'd6a1f1d1-a6e5-528f-9ef1-087013121739',
                                    },
                                    'd6a1f1d1-a6e5-528f-9ef1-087013121739',
                                    '2025-02-04T22:34:07.384000Z',
                                    1,
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
            expect(withinTable.getByTitle('This is the Gravatar for test@example.com')).toBeInTheDocument()
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

        // clicking person display link should navigate to person page
        userEvent.click(personDisplayLink)

        await waitFor(() => {
            expect(router.values.location.pathname).toBe(
                `/project/${MOCK_TEAM_ID}/persons/0257ab53-0816-55da-8919-73abbf36d5a9`
            )
        })
    })
})
