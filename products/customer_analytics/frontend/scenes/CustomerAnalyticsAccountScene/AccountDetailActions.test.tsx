import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { resetContext } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AccountDetailActions } from './AccountDetailActions'
import { accountViewsLogic } from './accountViewsLogic'

jest.mock('../../generated/api', () => ({ accountViewsList: jest.fn().mockResolvedValue([]) }))

describe('AccountDetailActions', () => {
    beforeEach(() => {
        resetContext()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.CUSTOMER_ANALYTICS_ACCOUNT_VIEWS]: true,
        })
    })

    afterEach(() => {
        cleanup()
        featureFlagLogic.unmount()
    })

    it('opens the personal account view editor', () => {
        const logic = accountViewsLogic({ projectId: 1 })
        logic.mount()
        render(<AccountDetailActions projectId={1} />)

        fireEvent.click(screen.getByText('New view'))

        expect(logic.values.editorOpen).toBe(true)
        logic.unmount()
    })
})
