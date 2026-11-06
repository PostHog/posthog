import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { DotMatrixSourcePicker } from './DotMatrixSourcePicker'

describe('DotMatrixSourcePicker', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it.each([false, true])('offers the product starter only with its flag (%s)', (enabled) => {
        featureFlagLogic.actions.setFeatureFlags([], { 'customer-analytics-product-usage': enabled })
        render(<DotMatrixSourcePicker id="source" value={null} onChange={jest.fn()} />)
        fireEvent.click(screen.getByTestId('account-dot-matrix-source'))
        expect(screen.queryByText('Product usage') !== null).toBe(enabled)
        expect(screen.getByText('Customer usage')).toBeTruthy()
        expect(screen.getByText('Custom HogQL')).toBeTruthy()
    })
})
