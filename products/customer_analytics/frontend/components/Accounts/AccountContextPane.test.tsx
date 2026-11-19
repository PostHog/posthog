import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import * as featureFlagLogic from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { AccountContextPane } from './AccountContextPane'

describe('AccountContextPane', () => {
    beforeEach(() => {
        initKeaTests()
        jest.spyOn(featureFlagLogic, 'getFeatureFlagPayload').mockReturnValue(null)
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it('keeps its content out of capture and shows write actions as disabled', async () => {
        const { container } = render(
            <Provider>
                <AccountContextPane accountId="account-1" externalId="external-account-1" />
            </Provider>
        )

        expect(await screen.findByText("Context isn't set up")).toBeInTheDocument()
        expect(container.firstElementChild).toHaveClass('ph-no-capture')
        expect(container.querySelector('[data-attr="account-context-add-fact"]')).toHaveAttribute(
            'aria-disabled',
            'true'
        )
    })
})
