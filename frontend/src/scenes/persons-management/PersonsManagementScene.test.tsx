import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import { router } from 'kea-router'
import { MOCK_TEAM_ID } from 'lib/api.mock'
import { rest } from 'msw'
import { urls } from 'scenes/urls'

import { mswServer } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AppContext } from '~/types'

import { PersonsManagementScene } from './PersonsManagementScene'
import { personsManagementSceneLogic } from './personsManagementSceneLogic'

describe('PersonsManagementScene', () => {
    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            current_team: { id: MOCK_TEAM_ID },
            current_project: { id: MOCK_TEAM_ID },
        } as unknown as AppContext

        initKeaTests()
        mswServer.use(
            rest.get(`/api/projects/:team_id/persons`, (req, res, ctx) => {
                const searchQuery = req.url.searchParams.get('search')
                if (searchQuery === 'test@example.com') {
                    return res(
                        ctx.json({
                            results: [
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
                            count: 1,
                        })
                    )
                }
                return res(ctx.json({ results: [], count: 0 }))
            }),
            rest.get(`/api/projects/:team_id/groups`, (req, res, ctx) => {
                return res(ctx.json({ results: [], count: 0 }))
            }),
            rest.get(`/api/projects/:team_id/property_definitions`, (req, res, ctx) => {
                return res(ctx.json({ results: [], count: 0 }))
            }),
            rest.post(`/api/environments/:team_id/query_awaited/`, (req, res, ctx) => {
                return res(
                    ctx.json({
                        results: [
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
                        count: 1,
                        complete: true,
                    })
                )
            })
        )
        router.actions.push(urls.persons())
    })

    it('can search for persons', async () => {
        const logic = personsManagementSceneLogic()
        logic.mount()

        render(
            <Provider>
                <PersonsManagementScene />
            </Provider>
        )

        const searchInput = screen.getByPlaceholderText('Search for persons')
        userEvent.type(searchInput, 'test@example.com')

        await waitFor(() => {
            expect(screen.getByText('Test User')).toBeInTheDocument()
            expect(screen.getByText('test@example.com')).toBeInTheDocument()
        })
    })
})
