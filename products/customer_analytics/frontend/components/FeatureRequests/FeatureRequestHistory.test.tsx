import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { FeatureRequestHistoryApi } from '../../generated/api.schemas'
import { FeatureRequestHistory } from './FeatureRequestHistory'

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
})
