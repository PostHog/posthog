import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { useRepositories } from './GitHubIntegrationHelpers'

// A mixed-case short name, so a key that lowercases every mode fails the default-mode test below.
const REPOS = [{ id: 1, name: 'HouseWatch', full_name: 'PostHog/HouseWatch', pushed_at: '2026-01-02T00:00:00Z' }]

function OptionKeysProbe({ valueKey }: { valueKey?: 'name' | 'full_name' }): JSX.Element {
    const { options, loading } = useRepositories(1, { valueKey })
    return <div data-attr="option-keys">{loading ? 'LOADING' : options.map((o) => o.key).join(',')}</div>
}

describe('useRepositories', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/:id/github_repos': () => [
                    200,
                    { repositories: REPOS, has_more: false, total: 1 },
                ],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    // The emitted `$github_event_received` event carries the qualified name (owner/repo), lowercased
    // to match the repository filter the API stores. A picker that keys its option on the short name
    // compiles a repository filter that no delivery can ever match. One that keeps GitHub's casing
    // leaves the stored value matching no option, so the picker offers it as a custom value beside
    // the real repository and drops that repository's rich label.
    it('keys options on the lowercased qualified name when valueKey is full_name', async () => {
        render(
            <Provider>
                <OptionKeysProbe valueKey="full_name" />
            </Provider>
        )
        await act(() => new Promise((r) => setTimeout(r, 500)))

        expect(screen.getByTestId('option-keys').textContent).toBe('posthog/housewatch')
    })

    it('keys options on the short name by default, unchanged for existing callers', async () => {
        render(
            <Provider>
                <OptionKeysProbe />
            </Provider>
        )
        await act(() => new Promise((r) => setTimeout(r, 500)))

        expect(screen.getByTestId('option-keys').textContent).toBe('HouseWatch')
    })
})
