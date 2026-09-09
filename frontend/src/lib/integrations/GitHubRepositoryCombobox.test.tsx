import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { GitHubRepositoryCombobox } from './GitHubRepositoryCombobox'

describe('GitHubRepositoryCombobox', () => {
    let hasMore: boolean
    let requests: number

    beforeEach(() => {
        hasMore = false
        requests = 0
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/:id/github_repos': () => {
                    const firstPage = requests++ === 0
                    return [
                        200,
                        {
                            repositories: [
                                {
                                    id: firstPage ? 1 : 2,
                                    name: firstPage ? 'archived' : 'active',
                                    full_name: firstPage ? 'example-org/archived' : 'example-org/active',
                                    archived: firstPage,
                                },
                            ],
                            has_more: firstPage && hasMore,
                        },
                    ]
                },
            },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    function renderFilteredPicker(onChange = jest.fn()): void {
        render(
            <Provider>
                <GitHubRepositoryCombobox
                    integrationId={123}
                    value=""
                    onChange={onChange}
                    repositoryFilter={(repo) => !repo.archived}
                />
            </Provider>
        )
    }

    it.each([
        { more: false, message: 'No repositories found.' },
        { more: true, message: 'No available repositories in these results. Load more to keep looking.' },
    ])('describes empty filtered results with hasMore=$more', async ({ more, message }) => {
        hasMore = more
        renderFilteredPicker()
        await userEvent.click(screen.getByRole('combobox'))
        expect(await screen.findByText(message)).toBeVisible()
        expect(!!screen.queryByRole('button', { name: 'Load more' })).toBe(more)
    })

    it('can select an available repository after loading past an archived-only page', async () => {
        hasMore = true
        const onChange = jest.fn()
        renderFilteredPicker(onChange)
        await userEvent.click(screen.getByRole('combobox'))
        await userEvent.click(await screen.findByRole('button', { name: 'Load more' }))
        await userEvent.click(await screen.findByRole('option', { name: 'example-org/active' }))
        expect(onChange).toHaveBeenCalledWith('example-org/active')
    })

    it('disables the trigger and exposes its explanation', async () => {
        render(
            <Provider>
                <GitHubRepositoryCombobox
                    integrationId={123}
                    value="example-org/active"
                    onChange={jest.fn()}
                    disabledReason="A cloud run is starting."
                />
            </Provider>
        )
        expect(screen.getByRole('combobox')).toHaveAttribute('aria-disabled', 'true')
        expect(screen.getByRole('combobox')).toHaveAccessibleDescription('A cloud run is starting.')
        expect(screen.getByRole('status')).toHaveTextContent('A cloud run is starting.')
        await userEvent.click(screen.getByRole('combobox'))
        expect(screen.getByRole('combobox')).toHaveAttribute('aria-expanded', 'false')
    })
})
