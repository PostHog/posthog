import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import * as featureFlagLogic from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { endpointsRunCreate } from 'products/endpoints/frontend/generated/api'

import { accountContextResponse } from '../../__mocks__/accountContextResponse'
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

    it.each([
        ['account-context-topic-filter', 'Feature flags'],
        ['account-context-author-filter', 'ada'],
        ['account-context-source-filter', 'Agent session'],
    ])('keeps the portaled %s menu out of capture', async (dataAttr, option) => {
        jest.spyOn(featureFlagLogic, 'getFeatureFlagPayload').mockReturnValue({
            project_id: 1,
            endpoint: 'account-context',
            account_variable: 'account_key',
        })
        runEndpoint.mockResolvedValue(
            accountContextResponse([
                {
                    section: 'fact',
                    id: 'fact-1',
                    fact_text: 'A confirmed fact',
                    confidence: 'confirmed',
                    author: 'ada@example.com',
                    fact_source: 'session',
                },
                { section: 'node', id: 'product:flags', node_kind: 'product', node_name: 'Feature flags' },
                { section: 'link', id: 'fact-1', to_id: 'product:flags', relation: 'about' },
            ])
        )
        const { container } = render(
            <Provider>
                <AccountContextPane accountId="account-1" externalId="external-account-1" />
            </Provider>
        )
        await screen.findByText('A confirmed fact')

        fireEvent.click(container.querySelector(`[data-attr="${dataAttr}"]`) as Element)

        await waitFor(() => {
            const menuOption = screen.getAllByText(option).find((element) => !container.contains(element))
            expect(menuOption?.closest('.ph-no-capture')).toBeInstanceOf(HTMLElement)
        })
    })
})
