import '@testing-library/jest-dom'

import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { router } from 'kea-router'
import { PersonsManagementScene } from 'scenes/persons-management/PersonsManagementScene'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

describe('PersonsManagementScene', () => {
    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query': (_req, res, ctx) => {
                    return res(
                        ctx.json({
                            results: [
                                [
                                    {
                                        id: 1,
                                        name: 'Test User',
                                        distinct_ids: ['test_id'],
                                        properties: {
                                            email: 'test@example.com',
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
})
