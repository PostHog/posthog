import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { useRepositories } from './GitHubIntegrationHelpers'

const REPOS = [{ id: 1, name: 'posthog', full_name: 'PostHog/posthog', pushed_at: '2026-01-02T00:00:00Z' }]

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

    // The emitted `$github_event_received` event carries the qualified name (owner/repo). A picker
    // that keys its option on the short name instead compiles a repository filter that no
    // delivery can ever match - the bug this option exists to avoid.
    it('keys options on the qualified name when valueKey is full_name', async () => {
        render(
            <Provider>
                <OptionKeysProbe valueKey="full_name" />
            </Provider>
        )
        await act(() => new Promise((r) => setTimeout(r, 500)))

        expect(screen.getByTestId('option-keys')).toHaveTextContent('PostHog/posthog')
    })

    it('keys options on the short name by default, unchanged for existing callers', async () => {
        render(
            <Provider>
                <OptionKeysProbe />
            </Provider>
        )
        await act(() => new Promise((r) => setTimeout(r, 500)))

        const content = screen.getByTestId('option-keys')
        expect(content).toHaveTextContent('posthog')
        expect(content.textContent).not.toBe('PostHog/posthog')
    })
})
