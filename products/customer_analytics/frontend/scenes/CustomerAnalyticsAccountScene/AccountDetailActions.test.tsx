import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { resetContext } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AccountDetailActions } from './AccountDetailActions'
import { accountViewsLogic } from './accountViewsLogic'

jest.mock('../../generated/api', () => ({
    accountViewsList: jest.fn().mockResolvedValue([]),
    userCustomerAnalyticsConfigRetrieve: jest.fn().mockResolvedValue({
        pinned_properties: [],
        task_digest: { enabled: false, send_time: '09:00', cadence: 'weekdays' },
        account_detail_tabs: { ordered_tab_ids: [], hidden_tab_ids: [], default_tab_id: null },
    }),
}))

describe('AccountDetailActions', () => {
    beforeEach(() => {
        resetContext()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_VIEWS]: true,
            [FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_TABS]: true,
        })
    })

    afterEach(() => {
        cleanup()
        featureFlagLogic.unmount()
    })

    it('opens the account view and tab configuration editors', async () => {
        const logic = accountViewsLogic({ projectId: 1 })
        logic.mount()
        render(<AccountDetailActions projectId={1} />)

        fireEvent.click(screen.getByText('New view'))
        expect(logic.values.editorOpen).toBe(true)

        await waitFor(() => expect(logic.values.config).not.toBeNull())
        fireEvent.click(screen.getByText('Configure tabs'))
        expect(logic.values.configureOpen).toBe(true)
        logic.unmount()
    })

    it('keeps Configure disabled until tab settings load, then initializes a pending draft from them', () => {
        const logic = accountViewsLogic({ projectId: 1 })
        logic.mount()
        render(<AccountDetailActions projectId={1} />)

        const configureButton = screen.getByText('Configure tabs').closest('button')
        expect(configureButton).toHaveAttribute('aria-disabled', 'true')

        logic.actions.openConfigure(null)
        logic.actions.loadConfigSuccess({
            pinned_properties: [],
            task_digest: { enabled: false, send_time: '09:00', cadence: 'weekdays' },
            account_detail_tabs: {
                ordered_tab_ids: ['system:users', 'system:notes'],
                hidden_tab_ids: ['system:notes'],
                default_tab_id: 'system:users',
            },
        })

        expect(logic.values.configDraft).toEqual({
            ordered_tab_ids: ['system:users', 'system:notes'],
            hidden_tab_ids: ['system:notes'],
            default_tab_id: 'system:users',
        })
        logic.unmount()
    })

    it('shows tab settings without account views', () => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_TABS]: true,
        })
        render(<AccountDetailActions projectId={1} />)

        expect(screen.getByText('Configure tabs')).toBeInTheDocument()
        expect(screen.queryByText('New view')).not.toBeInTheDocument()
    })
})
