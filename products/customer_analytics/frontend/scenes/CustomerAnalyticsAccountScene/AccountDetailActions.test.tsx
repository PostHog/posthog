import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
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
        })
    })
    afterEach(cleanup)

    it('opens the account view and tab configuration editors', () => {
        const logic = accountViewsLogic({ projectId: 1 })
        logic.mount()
        render(<AccountDetailActions projectId={1} />)

        fireEvent.click(screen.getByText('Add view'))
        expect(logic.values.editorOpen).toBe(true)

        fireEvent.click(screen.getByText('Configure tabs'))
        expect(logic.values.configureOpen).toBe(true)
        logic.unmount()
    })
})
