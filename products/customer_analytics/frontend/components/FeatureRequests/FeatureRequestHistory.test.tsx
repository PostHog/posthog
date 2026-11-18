import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { FeatureRequestHistoryApi } from '../../generated/api.schemas'
import { FeatureRequestHistory } from './FeatureRequestHistory'

const githubHistory: FeatureRequestHistoryApi[] = [
    {
        id: 'history-github-link',
        changes: [
            {
                field: 'github_link',
                before: null,
                after: {
                    id: 'github-link-1',
                    issue_url: 'https://github.com/posthog/posthog/issues/81886',
                    repository: 'posthog/posthog',
                    issue_number: 81886,
                    issue_title: 'Export account-level retention data',
                    issue_state: 'open',
                    sync_enabled: true,
                },
            },
        ],
        is_initial: false,
        change_source: 'github',
        actor_id: null,
        actor_name: null,
        changed_at: '2026-01-03T00:00:00Z',
    },
    {
        id: 'history-github-paused',
        changes: [{ field: 'github_sync', before: true, after: false }],
        is_initial: false,
        change_source: 'github',
        actor_id: null,
        actor_name: null,
        changed_at: '2026-01-03T01:00:00Z',
    },
    {
        id: 'history-github-resumed',
        changes: [{ field: 'github_sync', before: false, after: true }],
        is_initial: false,
        change_source: 'github',
        actor_id: null,
        actor_name: null,
        changed_at: '2026-01-03T02:00:00Z',
    },
    {
        id: 'history-github-unlink',
        changes: [
            {
                field: 'github_link',
                before: {
                    id: 'github-link-1',
                    issue_url: 'https://github.com/posthog/posthog/issues/81886',
                    repository: 'posthog/posthog',
                    issue_number: 81886,
                    issue_title: 'Export account-level retention data',
                    issue_state: 'open',
                    sync_enabled: false,
                },
                after: null,
            },
        ],
        is_initial: false,
        change_source: 'github',
        actor_id: null,
        actor_name: null,
        changed_at: '2026-01-03T03:00:00Z',
    },
]

const history: FeatureRequestHistoryApi[] = [
    {
        id: 'history-evidence',
        changes: [
            {
                field: 'evidence',
                before: null,
                after: {
                    id: 'evidence-1',
                    account: { id: 'account-1', name: 'Acme' },
                    summary: 'Acme needs weekly exports.',
                    customer_quote: '',
                    source: 'conversation',
                    source_url: '',
                    requested_on: '2026-01-03',
                },
            },
        ],
        is_initial: false,
        change_source: 'manual',
        actor_id: 1,
        actor_name: 'Test user',
        changed_at: '2026-01-03T00:00:00Z',
    },
    {
        id: 'history-github',
        changes: [{ field: 'status', before: 'planned', after: 'completed' }],
        is_initial: false,
        change_source: 'github',
        actor_id: null,
        actor_name: null,
        changed_at: '2026-01-03T01:00:00Z',
    },
    {
        id: 'history-account',
        changes: [
            {
                field: 'accounts',
                before: [{ id: 'account-1', name: 'Acme' }],
                after: [
                    { id: 'account-1', name: 'Acme' },
                    { id: 'account-2', name: 'Globex' },
                ],
            },
        ],
        is_initial: false,
        change_source: 'manual',
        actor_id: 1,
        actor_name: 'Test user',
        changed_at: '2026-01-02T00:00:00Z',
    },
]

describe('FeatureRequestHistory', () => {
    afterEach(cleanup)

    it('reveals the account or evidence referenced by a history entry', () => {
        const onShowTarget = jest.fn()
        render(
            <FeatureRequestHistory
                history={history}
                loading={false}
                error={null}
                showingAll
                onRetry={jest.fn()}
                onSetShowingAll={jest.fn()}
                onShowTarget={onShowTarget}
            />
        )

        fireEvent.click(screen.getByText('Evidence:'))
        expect(onShowTarget).toHaveBeenLastCalledWith('account-1', 'evidence-1')

        fireEvent.click(screen.getByText('Accounts:'))
        expect(onShowTarget).toHaveBeenLastCalledWith('account-2', undefined)
    })

    it('describes GitHub links and sync changes without showing raw history data', () => {
        render(
            <FeatureRequestHistory
                history={githubHistory}
                loading={false}
                error={null}
                showingAll
                onRetry={jest.fn()}
                onSetShowingAll={jest.fn()}
                onShowTarget={jest.fn()}
            />
        )

        expect(
            screen.getByText('linked posthog/posthog#81886 (Export account-level retention data)')
        ).toBeInTheDocument()
        expect(screen.getByText('paused')).toBeInTheDocument()
        expect(screen.getByText('resumed')).toBeInTheDocument()
        expect(
            screen.getByText('unlinked posthog/posthog#81886 (Export account-level retention data)')
        ).toBeInTheDocument()
    })

    it.each([
        ['a recorded actor', { actor_id: 1, actor_name: 'Test user' }, 'Test user updated this request'],
        ['an actorless GitHub entry', { actor_id: null, actor_name: null }, 'GitHub updated this request'],
    ])('identifies %s in GitHub history', (_, actor, expectedLabel) => {
        render(
            <FeatureRequestHistory
                history={[{ ...githubHistory[0], ...actor }]}
                loading={false}
                error={null}
                showingAll
                onRetry={jest.fn()}
                onSetShowingAll={jest.fn()}
                onShowTarget={jest.fn()}
            />
        )

        expect(screen.getByText(expectedLabel)).toBeInTheDocument()
    })
})
