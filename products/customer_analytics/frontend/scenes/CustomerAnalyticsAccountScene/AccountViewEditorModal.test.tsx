import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { resetContext } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { accountViewsList, accountViewsPartialUpdate, userCustomerAnalyticsConfigRetrieve } from '../../generated/api'
import type { AccountViewApi } from '../../generated/api.schemas'
import { createAccountViewContent } from './accountViewDocument'
import { AccountViewEditorModal } from './AccountViewEditorModal'
import { accountViewsLogic } from './accountViewsLogic'

const visibilityOnlyTeamView: AccountViewApi = {
    id: '11111111-2222-4333-8444-555555555555',
    name: 'Restricted team view',
    visibility: 'team',
    content: createAccountViewContent([{ nodeId: 'usage-one', kind: 'usage', span: 12, title: 'Usage' }]),
    text_content: 'Usage',
    version: 1,
    created_by: 2,
    last_modified_by: 2,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    can_edit: false,
    can_delete: true,
    can_change_visibility: true,
}

const editableCustomSpanView: AccountViewApi = {
    ...visibilityOnlyTeamView,
    content: createAccountViewContent([{ nodeId: 'usage-one', kind: 'usage', span: 7, title: 'Usage' }]),
    can_edit: true,
}

jest.mock('../../generated/api', () => ({
    accountViewsList: jest.fn(),
    accountViewsPartialUpdate: jest.fn(),
    userCustomerAnalyticsConfigRetrieve: jest.fn(),
}))

const mockAccountViewsList = accountViewsList as jest.MockedFunction<typeof accountViewsList>
const mockAccountViewsPartialUpdate = accountViewsPartialUpdate as jest.MockedFunction<typeof accountViewsPartialUpdate>
const mockUserCustomerAnalyticsConfigRetrieve = userCustomerAnalyticsConfigRetrieve as jest.MockedFunction<
    typeof userCustomerAnalyticsConfigRetrieve
>

describe('AccountViewEditorModal', () => {
    beforeEach(() => {
        resetContext()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {})
        mockAccountViewsList.mockResolvedValue([visibilityOnlyTeamView])
        mockAccountViewsPartialUpdate.mockResolvedValue({
            ...visibilityOnlyTeamView,
            visibility: 'private',
            version: 2,
        })
        mockUserCustomerAnalyticsConfigRetrieve.mockResolvedValue({
            pinned_properties: [],
            task_digest: { enabled: false, send_time: '09:00', cadence: 'weekdays' },
            account_detail_tabs: { ordered_tab_ids: [], hidden_tab_ids: [], default_tab_id: null },
        })
        mockAccountViewsPartialUpdate.mockClear()
    })

    afterEach(() => {
        cleanup()
        featureFlagLogic.unmount()
    })

    it('shows the actual value for a stored custom tile span', async () => {
        mockAccountViewsList.mockResolvedValue([editableCustomSpanView])
        const logic = accountViewsLogic({ projectId: 1 })
        logic.mount()
        render(<AccountViewEditorModal projectId={1} />)

        await waitFor(() => expect(logic.values.views).toEqual([editableCustomSpanView]))
        act(() => logic.actions.openEditEditor(editableCustomSpanView))

        expect(screen.getByText('Custom (7/12)')).toBeInTheDocument()
        logic.unmount()
    })

    it('allows a visibility-only team view editor to save only the visibility', async () => {
        const logic = accountViewsLogic({ projectId: 1 })
        logic.mount()
        render(<AccountViewEditorModal projectId={1} />)

        await waitFor(() => expect(logic.values.views).toEqual([visibilityOnlyTeamView]))
        act(() => logic.actions.openEditEditor(visibilityOnlyTeamView))

        expect(screen.getByText('Change view visibility')).toBeInTheDocument()
        expect(document.querySelector('[data-attr="account-view-name"]')).not.toBeInTheDocument()
        expect(screen.queryByText('Components')).not.toBeInTheDocument()
        expect(
            screen.getByText(
                "You can change this view's visibility, but only account editors can change its name or contents."
            )
        ).toBeInTheDocument()

        fireEvent.click(screen.getByText('Only me'))
        fireEvent.click(screen.getByText('Save visibility'))

        await waitFor(() =>
            expect(mockAccountViewsPartialUpdate).toHaveBeenCalledWith('1', visibilityOnlyTeamView.id, {
                visibility: 'private',
                version: visibilityOnlyTeamView.version,
            })
        )
        logic.unmount()
    })
})
