import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'
import type { ReactNode } from 'react'

import { initKeaTests } from '~/test/init'

import { AIObservabilitySelfDriving } from './AIObservabilitySelfDriving'

jest.mock('products/signals/frontend/generated/api', () => ({
    signalsScoutConfigList: jest.fn(() => new Promise(() => {})),
    signalsScoutMetadataGet: jest.fn(() => new Promise(() => {})),
}))

jest.mock('products/signals/frontend/inbox/components/config/scouts/ScoutCreateButton', () => ({
    ScoutCreateButton: ({ children }: { children: ReactNode }) => <button>{children}</button>,
}))

describe('AIObservabilitySelfDriving', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders scout templates and links to the self-driving docs', async () => {
        render(
            <Provider>
                <AIObservabilitySelfDriving />
            </Provider>
        )

        expect(screen.getAllByText('Use template')).toHaveLength(3)

        const tooltipTrigger = screen.getByText('What is this?')
        await userEvent.hover(tooltipTrigger)

        expect(await screen.findByText(/Each template is a pre-defined scout/)).toBeInTheDocument()

        const docsLink = screen.getByText('Read the docs')
        expect(docsLink).toHaveAttribute('href', 'https://posthog.com/docs/ai-observability/self-driving')
        expect(docsLink).toHaveAttribute('target', '_blank')
        expect(screen.getByText('ai-observability').closest('p')).toHaveTextContent(
            'Add the ai-observability label to a scout for it to appear here.'
        )
    })
})
