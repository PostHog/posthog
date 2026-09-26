import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'
import { resetContext } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { AccountViewApi } from '../../generated/api.schemas'
import { createAccountViewContent } from './accountViewDocument'
import { AccountViewRenderer } from './AccountViewRenderer'
import { accountViewsLogic } from './accountViewsLogic'

jest.mock('./AccountViewTile', () => {
    const React = jest.requireActual<typeof import('react')>('react')

    return {
        AccountViewTile: ({ component }: { component: { config?: { searchTerm?: string } } }) => {
            const [mountedSearchTerm] = React.useState(component.config?.searchTerm)
            return React.createElement('span', { 'data-attr': 'mounted-search-term' }, mountedSearchTerm)
        },
    }
})

function createView(searchTerm: string): AccountViewApi {
    return {
        id: '11111111-2222-4333-8444-555555555555',
        name: 'Account view',
        visibility: 'private',
        content: createAccountViewContent([
            {
                nodeId: 'tile-1',
                kind: 'notes',
                span: 12,
                config: { searchTerm },
            },
        ]),
        text_content: '',
        version: 1,
        created_by: 1,
        last_modified_by: 1,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        can_edit: true,
        can_delete: true,
        can_change_visibility: true,
    }
}

describe('AccountViewRenderer', () => {
    beforeEach(() => {
        resetContext()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {})
    })

    afterEach(() => {
        cleanup()
        featureFlagLogic.unmount()
    })

    it('remounts a tile only after a failed save reloads persisted config at the same version', () => {
        const { rerender } = render(
            <AccountViewRenderer
                view={createView('optimistic')}
                projectId={1}
                accountId="account-1"
                externalId="external-account-1"
            />
        )

        expect(screen.getByTestId('mounted-search-term')).toHaveTextContent('optimistic')

        rerender(
            <AccountViewRenderer
                view={createView('persisted')}
                projectId={1}
                accountId="account-1"
                externalId="external-account-1"
            />
        )

        expect(screen.getByTestId('mounted-search-term')).toHaveTextContent('optimistic')
        act(() =>
            accountViewsLogic({ projectId: 1 }).actions.resetViewComponentConfig('11111111-2222-4333-8444-555555555555')
        )
        expect(screen.getByTestId('mounted-search-term')).toHaveTextContent('persisted')
    })
})
