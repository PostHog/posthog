import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import * as featureFlagLogic from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { endpointsRunCreate } from 'products/endpoints/frontend/generated/api'

import { AccountContextPane } from './AccountContextPane'

jest.mock('products/endpoints/frontend/generated/api', () => ({
    ...jest.requireActual('products/endpoints/frontend/generated/api'),
    endpointsRunCreate: jest.fn(),
}))

const runEndpoint = jest.mocked(endpointsRunCreate)

class ResizeObserverMock {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
}

describe('AccountContextPane', () => {
    beforeAll(() => {
        ;(global as typeof globalThis & { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
            ResizeObserverMock as unknown as typeof ResizeObserver
    })

    beforeEach(() => {
        initKeaTests()
        runEndpoint.mockReset()
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

    it('keeps the portaled filter menus out of capture', async () => {
        jest.spyOn(featureFlagLogic, 'getFeatureFlagPayload').mockReturnValue({
            project_id: 1,
            endpoint: 'account-context',
            account_variable: 'account_key',
        })
        runEndpoint.mockResolvedValue({
            name: 'account-context',
            columns: ['section', 'id', 'fact_text', 'confidence', 'node_kind', 'node_name', 'to_id', 'relation'],
            results: [
                ['fact', 'fact-1', 'A confirmed fact', 'confirmed', null, null, null, null],
                ['node', 'product:flags', null, null, 'product', 'Feature flags', null, null],
                ['link', 'fact-1', null, null, null, null, 'product:flags', 'about'],
            ],
        })
        const { container } = render(
            <Provider>
                <AccountContextPane accountId="account-1" externalId="external-account-1" />
            </Provider>
        )
        await screen.findByText('A confirmed fact')

        fireEvent.click(container.querySelector('[data-attr="account-context-topic-filter"]') as Element)

        await waitFor(() => {
            const menuOption = screen.getAllByText('Feature flags').find((element) => !container.contains(element))
            expect(menuOption?.closest('.ph-no-capture')).not.toBeNull()
        })
    })
})
